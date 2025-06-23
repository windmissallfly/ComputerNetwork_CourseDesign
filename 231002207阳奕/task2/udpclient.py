import socket
import struct
import time
import random
from collections import deque
import pandas as pd
import threading
import sys

# 自定义协议头部格式
HEADER_FMT = ">IIBQH"  # 序列号(4字节) + 确认号(4字节) + 标志(1字节) + 时间戳(8字节) + 数据长度(2字节)
HEADER_SIZE = struct.calcsize(HEADER_FMT)

# 标志位定义
FLAG_SYN = 0x1
FLAG_ACK = 0x2
FLAG_DATA = 0x4
FLAG_FIN = 0x8


class GBNClient:
    def __init__(self, server_ip, server_port, timeout=0.3, loss_rate=0.3):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)  # 设置接收超时时间
        self.server_addr = (server_ip, server_port)
        self.window_size = 400  # 字节
        self.timeout = timeout  # 秒
        self.base_seq = 0  # 窗口起始序列号
        self.next_seq = 0  # 下一个可用的序列号
        self.packets = {}  # 存储已发送但未确认的包 {seq: (data, 发送时间)}
        self.packet_info = {}  # 包详细信息记录
        self.rtt_samples = []  # RTT样本
        self.timer_active = True
        self.is_connected = False
        self.total_packets = 0
        self.loss_rate = loss_rate
        self.expected_ack = 0
        self.lock = threading.Lock()
        self.data_sent = False
        self.finish_event = threading.Event()
        self.receiver_thread = None

    def connect(self):
        """建立连接（三次握手）"""
        syn_timeout = 1.0  # SYN超时时间稍长

        # 第一次握手：发送SYN
        print("Sending SYN to server...")
        self._send_packet(seq=0, ack=0, flags=FLAG_SYN, data=b'')
        self.expected_ack = 1  # 期望的确认号

        # 第二次握手：等待SYN-ACK
        while not self.is_connected:
            try:
                data, addr = self.sock.recvfrom(1024)
                if addr != self.server_addr:
                    continue

                # 解析包头
                seq, ack, flags, ts, data_len = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])

                # 检查是否是有效的SYN-ACK
                if flags & FLAG_SYN and flags & FLAG_ACK and ack == self.expected_ack:
                    # 第三次握手：发送ACK
                    print(f"Received SYN-ACK, seq={seq}, ack={ack}")
                    self._send_packet(seq=1, ack=seq + 1, flags=FLAG_ACK, data=b'')
                    self.is_connected = True
                    print("Connection established")

                    # 初始化序列号
                    self.base_seq = 1
                    self.next_seq = 1
                    return True
            except socket.timeout:
                print("Timeout waiting for SYN-ACK, retrying...")
                self._send_packet(seq=0, ack=0, flags=FLAG_SYN, data=b'')

        return False

    def send_data(self, data_bytes, min_chunk=40, max_chunk=80):
        """发送数据（使用GBN协议）"""
        if not self.is_connected:
            print("Not connected to server")
            return

        # 启动接收线程
        self.receiver_thread = threading.Thread(target=self._receive)
        self.receiver_thread.daemon = True
        self.receiver_thread.start()

        # 启动定时器线程
        timer_thread = threading.Thread(target=self._timeout_check)
        timer_thread.daemon = True
        timer_thread.start()

        # 计算数据总量和起始字节位置
        total_length = len(data_bytes)
        byte_pos = 0

        # 分段发送数据
        while byte_pos < total_length or self.packets:
            with self.lock:
                # 计算当前窗口已用空间
                window_used = sum(len(data) for data, _ in self.packets.values())
                window_available = self.window_size - window_used

                # 窗口有空间时发送新数据
                if window_available > 0 and byte_pos < total_length:
                    # 随机确定数据块大小
                    chunk_size = min(max_chunk, min(window_available, total_length - byte_pos))
                    if chunk_size < min_chunk and chunk_size < total_length - byte_pos:
                        chunk_size = min(min_chunk, total_length - byte_pos)

                    # 获取数据块
                    data_chunk = data_bytes[byte_pos:byte_pos + chunk_size]

                    # 发送数据包
                    self._send_data_packet(data_chunk)

                    # 记录包信息（用于日志）
                    self.packet_info[self.total_packets] = {
                        'start_byte': byte_pos,
                        'end_byte': byte_pos + chunk_size - 1,
                        'sent_time': time.time(),
                        'ack_received': False,
                        'retransmissions': 0
                    }

                    # 打印发送日志
                    print(f"第{self.total_packets}个(第{byte_pos}~{byte_pos + chunk_size - 1}字节)client端已经发送")

                    byte_pos += chunk_size
                    self.total_packets += 1

            # 短暂休眠避免忙等待
            time.sleep(0.01)

        self.data_sent = True

        # 等待所有ACK
        while self.packets:
            time.sleep(0.1)

        # 关闭连接
        self._send_packet(seq=self.next_seq, ack=0, flags=FLAG_FIN, data=b'FIN')
        self.finish_event.set()

        # 生成报告
        self.generate_report()

    def _send_data_packet(self, data_chunk):
        """发送数据包"""
        timestamp = int(time.time() * 1e6)  # 微秒
        packet_length = len(data_chunk)
        header = struct.pack(HEADER_FMT, self.next_seq, 0, FLAG_DATA, timestamp, packet_length)
        packet = header + data_chunk
        self.sock.sendto(packet, self.server_addr)

        # 记录已发送但未确认的包
        self.packets[self.next_seq] = (data_chunk, time.time())
        self.next_seq += 1

    def _timeout_check(self):
        """定时检查超时包"""
        while not self.finish_event.is_set():
            current_time = time.time()
            timeouts = []

            with self.lock:
                # 查找所有超时包
                for seq, (_, sent_time) in self.packets.items():
                    if current_time - sent_time > self.timeout:
                        timeouts.append(seq)

                # 处理超时包（GBN协议：回退到base_seq重新发送所有未确认包）
                if timeouts:
                    min_timeout = min(timeouts)
                    print(f"Timeout detected, resending packets from {self.base_seq} to {self.next_seq - 1}")

                    # 记录重传次数
                    for seq in self.packets:
                        if seq not in self.packet_info:
                            continue
                        self.packet_info[seq]['retransmissions'] += 1
                        data_range = (self.packet_info[seq]['start_byte'],
                                      self.packet_info[seq]['end_byte'])
                        print(f"重传第{seq}个(第{data_range[0]}~{data_range[1]}字节)数据包")

                    # 重新发送所有未确认包
                    for seq in sorted(self.packets.keys()):
                        _, sent_time = self.packets[seq]
                        packet_data = self.packets[seq][0]
                        timestamp = int(time.time() * 1e6)
                        header = struct.pack(HEADER_FMT, seq, 0, FLAG_DATA, timestamp, len(packet_data))
                        self.sock.sendto(header + packet_data, self.server_addr)
                        self.packets[seq] = (packet_data, time.time())

            time.sleep(self.timeout / 2)  # 检查频率为超时时间的一半

    def _receive(self):
        """接收ACK包"""
        while not self.finish_event.is_set():
            try:
                data, addr = self.sock.recvfrom(1024)
                if addr != self.server_addr:
                    continue

                # 解析包头
                if len(data) < HEADER_SIZE:
                    continue

                header = data[:HEADER_SIZE]
                seq, ack, flags, ts, length = struct.unpack(HEADER_FMT, header)
                payload = data[HEADER_SIZE:HEADER_SIZE + length]

                # 处理ACK包
                if flags & FLAG_ACK:
                    # 更新base_seq
                    self.base_seq = max(self.base_seq, ack)

                    # 从packets字典中移除已确认的包
                    with self.lock:
                        # 收集所有已确认的序列号
                        acked_seqs = [s for s in self.packets.keys() if s < ack]

                        for s in acked_seqs:
                            if s in self.packets:
                                # 记录RTT
                                sent_time = self.packets[s][1]
                                rtt = (time.time() - sent_time) * 1000  # 毫秒
                                self.rtt_samples.append(rtt)

                                # 打印接收日志
                                if s in self.packet_info:
                                    self.packet_info[s]['ack_received'] = True
                                    start = self.packet_info[s]['start_byte']
                                    end = self.packet_info[s]['end_byte']
                                    print(f"第{s}个(第{start}~{end}字节)server端已经收到，RTT是{rtt:.2f}ms")

                                # 从字典中移除已确认包
                                del self.packets[s]

                        # 动态调整超时时间（平均RTT的5倍）
                        if self.rtt_samples:
                            avg_rtt = sum(self.rtt_samples) / len(self.rtt_samples)
                            self.timeout = max(0.1, avg_rtt * 5 / 1000)  # 转换为秒
                            print(
                                f"Updated timeout to {self.timeout * 1000:.2f}ms based on average RTT {avg_rtt:.2f}ms")

                        # 计算并打印当前时间（HH:MM:SS格式）
                        current_time = time.strftime("%H-%M-%S")
                        print(f"Server time: {current_time}")

            except socket.timeout:
                # 超时是正常现象，继续等待
                continue
            except Exception as e:
                print(f"Receive error: {e}")
                break

    def generate_report(self):
        """生成传输报告"""
        if not self.packet_info:
            print("No packets sent, cannot generate report")
            return

        # 计算丢包率（重传包占总发送包的比例）
        total_packets_sent = len(self.packet_info)
        total_retransmissions = sum(info['retransmissions'] for info in self.packet_info.values())
        loss_rate = (total_retransmissions / total_packets_sent) * 100

        # 计算RTT统计信息
        if self.rtt_samples:
            df = pd.DataFrame(self.rtt_samples, columns=['rtt'])
            max_rtt = df['rtt'].max()
            min_rtt = df['rtt'].min()
            avg_rtt = df['rtt'].mean()
            std_rtt = df['rtt'].std()
        else:
            max_rtt = min_rtt = avg_rtt = std_rtt = 0

        # 打印报告
        print("\n====== Transmission Report ======")
        print(f"Total packets sent: {total_packets_sent}")
        print(f"Total retransmissions: {total_retransmissions}")
        print(f"Packet loss rate: {loss_rate:.2f}%")
        print(f"Maximum RTT: {max_rtt:.2f}ms")
        print(f"Minimum RTT: {min_rtt:.2f}ms")
        print(f"Average RTT: {avg_rtt:.2f}ms")
        print(f"RTT Standard Deviation: {std_rtt:.2f}ms")


def main():
    # 命令行参数: python udpclient.py <server_ip> <server_port> [loss_rate] [timeout]
    if len(sys.argv) < 3:
        print("Usage: python udpclient.py <server_ip> <server_port> [loss_rate=0.3] [timeout=0.3]")
        return

    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    loss_rate = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
    timeout = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3

    # 生成测试数据 (2000字节)
    data = b''
    for i in range(100):
        data += f"Packet {i} ".encode() + b'x' * 20

    client = GBNClient(server_ip, server_port, timeout, loss_rate)

    if client.connect():
        client.send_data(data)


if __name__ == "__main__":
    main()