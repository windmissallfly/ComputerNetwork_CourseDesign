import socket
import struct
import time
import random
import pandas as pd
import threading
import sys

# 自定义协议首部格式
# I：4字节，B：1字节，Q：8字节，H：2字节
header_Format = ">IIBQH"  # 序列号(4字节) + 确认号(4字节) + 标志(1字节) + 时间戳(8字节) + 数据长度(2字节)
header_Size = struct.calcsize(header_Format)

# 标志位定义
flag_SYN = 0x1
flag_ACK = 0x2
flag_DATA = 0x4
flag_FIN = 0x8


class GBNClient:

    # udpclient.py代码中没有显式绑定端口（GBNClient类初始化时没有调用bind()）
    # 但是为了确保客户端知道自己要连接哪个服务器，所以必须显示指定一个监听端口，所有客户端线程共享这个端口
    # 所以当一个客户端第一次发送数据时，操作系统会自动分配一个临时端口给这个客户端，与其他客户端区分开
    def __init__(self, server_ip, server_port, timeout=0.3, loss_rate=0.3):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)  # 设置接收超时时间
        self.server_addr = (server_ip, server_port)
        self.window_size = 400  # 字节
        self.packet_size = 80  # 固定每个包80字节
        self.max_in_flight = 5  # 窗口最多容纳5个包 (400/80=5)
        self.timeout = timeout  # 秒
        self.base_seq = 0  # 窗口起始序列号
        self.next_seq = 0  # 下一个可用的序列号
        self.packets = {}  # 存储已发送但未确认的包 {seq: (data, 发送时间)}
        self.packet_info = {}  # 包详细信息记录
        self.rtt_samples = []  # RTT样本
        self.packet_counter = 0  # 全局包计数器
        self.timer_active = True
        self.is_connected = False
        self.total_packets = 0
        self.loss_rate = loss_rate
        self.expected_ack = 0
        self.lock = threading.Lock()
        self.data_sent = False
        self.finish_event = threading.Event()
        self.receiver_thread = None

    def send_packet(self, seq, ack, flags, data):
        """发送控制包（SYN/ACK/FIN）"""
        timestamp = int(time.time() * 1e6)  # 微秒
        packet_length = len(data)
        header = struct.pack(header_Format, seq, ack, flags, timestamp, packet_length)
        packet = header + data

        # 模拟丢包
        if random.random() < self.loss_rate and flags != flag_SYN:  # SYN包不模拟丢包
            print(f"模拟丢包: seq={seq}, flags={flags}")
            return

        self.sock.sendto(packet, self.server_addr)
        print(f"发送包信息: seq={seq}, ack={ack}, flags={flags}, size={packet_length}")

    def connect(self):
        """建立连接（三次握手）"""
        syn_timeout = 1.0  # SYN超时时间稍长

        # 第一次握手：发送SYN
        print("发送SYN给服务器...")
        self.send_packet(seq=0, ack=0, flags=flag_SYN, data=b'')
        self.expected_ack = 1  # 期望的确认号

        # 第二次握手：等待SYN-ACK
        while not self.is_connected:
            try:
                data, addr = self.sock.recvfrom(1024)
                if addr != self.server_addr:
                    continue

                # 解析包头
                seq, ack, flags, ts, data_len = struct.unpack(header_Format, data[:header_Size])

                # 检查是否是有效的SYN-ACK
                if flags & flag_SYN and flags & flag_ACK and ack == self.expected_ack:
                    # 第三次握手：发送ACK
                    print(f"接收SYN-ACK, seq={seq}, ack={ack}")
                    self.send_packet(seq=1, ack=seq + 1, flags=flag_ACK, data=b'')
                    self.is_connected = True
                    print("连接建立")

                    # 初始化序列号
                    self.base_seq = 1
                    self.next_seq = 1
                    return True
            except socket.timeout:
                print("等待SYN-ACK超时，重试...")
                self.send_packet(seq=0, ack=0, flags=flag_SYN, data=b'')

        return False

    def send_data(self, data_bytes):
        """发送数据（使用GBN协议）"""
        if not self.is_connected:
            print("未连接到服务器")
            return

        # 启动接收线程
        self.receiver_thread = threading.Thread(target=self.receive)
        self.receiver_thread.daemon = True
        self.receiver_thread.start()

        # 启动定时器线程
        timer_thread = threading.Thread(target=self.timeout_check)
        timer_thread.daemon = True
        timer_thread.start()

        # 计算数据总量和起始字节位置
        total_length = len(data_bytes)
        byte_pos = 0
        packet_count = 0  # 包计数器

        # 分段发送数据
        while packet_count < 50 or self.packets:
            with self.lock:
                # 计算当前窗口可用空间（按照包的数目计算）
                window_available = self.max_in_flight - len(self.packets)

                # 发送新数据包（如果窗口有空间且未达50个包）
                while window_available > 0 and packet_count < 50:
                    # 获取固定80字节的数据块（最后不足80则取剩余）
                    end_pos = min(byte_pos + self.packet_size, total_length)
                    data_piece = data_bytes[byte_pos:end_pos]

                    # 发送数据包
                    self.send_data_packet(data_piece)

                    # 记录包信息（用于日志）
                    self.packet_info[self.total_packets] = {
                        'start_byte': byte_pos,
                        'end_byte': byte_pos + len(data_piece) - 1,
                        'sent_time': time.time(),
                        'ack_received': False,
                        'retransmissions': 0,
                        'send_count': 0,
                        'first_sent': time.time()
                    }

                    # 打印发送日志
                    print(f"第{packet_count}个(第{byte_pos}~{byte_pos + len(data_piece) - 1}字节)client端已经发送")

                    byte_pos += len(data_piece)
                    packet_count += 1
                    window_available -= 1

            # 短暂休眠避免忙等待
            time.sleep(0.01)

        self.data_sent = True

        # 等待所有ACK
        while self.packets:
            time.sleep(0.1)

        # 关闭连接
        self.send_packet(seq=self.next_seq, ack=0, flags=flag_FIN, data=b'FIN')
        self.finish_event.set()

        # 生成报告
        self.generate_report()

    def send_data_packet(self, data_piece):
        """发送数据包"""
        seq = self.next_seq
        if seq not in self.packet_info:
            self.packet_info[seq] = {
                'send_count': 0,
                'first_sent': time.time(),
                'retransmissions': 0,
                'ack_received': False,
                'start_byte': 0,
                'end_byte': 0
            }
        self.packet_info[seq]['send_count'] += 1

        timestamp = int(time.time() * 1e6)  # 微秒
        packet_length = len(data_piece)
        header = struct.pack(header_Format, self.next_seq, 0, flag_DATA, timestamp, packet_length)
        packet = header + data_piece

        # 模拟丢包
        if random.random() < self.loss_rate:
            print(f"模拟数据包丢包: seq={self.next_seq}")
            return

        self.sock.sendto(packet, self.server_addr)

        # 记录已发送但未确认的包
        self.packets[self.next_seq] = (data_piece, time.time())
        self.next_seq += 1

    def timeout_check(self):
        """定时检查超时包"""
        while not self.finish_event.is_set():
            current_time = time.time()

            with self.lock:
                # 检查所有未确认包是否超时
                if self.packets and (current_time - min(t for _, t in self.packets.values())) > self.timeout:
                    print(f"超时！从{self.base_seq}开始重传窗口内所有包")

                    # 记录重传
                    try:
                        for seq in range(self.base_seq, self.next_seq):
                            if seq in self.packet_info:
                                self.packet_info[seq]['retransmissions'] += 1
                                print(f"重传第{seq}个包")

                        # 重传所有未确认包
                        for seq in sorted(self.packets.keys()):
                            data_piece, _ = self.packets[seq]
                            self.send_data_packet(data_piece)  # 重新发送
                            self.packets[seq] = (data_piece, time.time())  # 更新发送时间

                    except Exception as e:
                        print(f"超时检查错误: {e}")
                        continue

            time.sleep(self.timeout / 2)  # 检查频率为超时时间的一半

    def receive(self):
        """接收ACK包（GBN协议实现）"""
        while not self.finish_event.is_set():
            try:
                data, addr = self.sock.recvfrom(1024)
                if addr != self.server_addr:
                    continue

                # 解析包头
                if len(data) < header_Size:
                    continue

                header = data[:header_Size]
                seq, ack, flags, ts, length = struct.unpack(header_Format, header)

                server_time = self.timestamp_to_time(ts)
                print(f"服务器系统时间: {server_time}")

                # 处理ACK包
                if flags & flag_ACK:
                    if seq in self.packet_info:
                        rtt = (time.time() - self.packet_info[seq]['first_sent']) * 1000
                        self.rtt_samples.append(rtt)

                    # GBN累积确认处理
                    with self.lock:
                        if ack > self.base_seq:
                            # 处理所有被确认的包
                            for s in range(self.base_seq, ack):
                                if s in self.packets:
                                    # 计算RTT
                                    sent_time = self.packets[s][1]
                                    rtt = (time.time() - sent_time) * 1000  # 毫秒
                                    self.rtt_samples.append(rtt)

                                    # 更新包状态
                                    if s in self.packet_info:
                                        self.packet_info[s]['ack_received'] = True
                                        print(f"第{s}个包确认(RTT={rtt:.2f}ms)")

                                    del self.packets[s]  # 从窗口中移除

                            # 滑动窗口
                            self.base_seq = ack

                            # 动态调整超时时间（基于平均RTT）
                            if self.rtt_samples:
                                avg_rtt = sum(self.rtt_samples) / len(self.rtt_samples)
                                self.timeout = min(100, avg_rtt * 5) / 1000 # 上限100ms，单位为ms
                                print(f"调整超时时间为: {self.timeout * 1000:.2f}ms 基于平均RTT{avg_rtt:.2f}ms")

            except socket.timeout:
                continue  # 超时是正常现象
            except Exception as e:
                print(f"接收错误: {e}")
                break

    def timestamp_to_time(self, timestamp):
        """将时间戳转换为可读时间格式（HH:MM:SS）"""
        # timestamp是微秒级时间戳（来自包头）
        seconds = timestamp / 1e6  # 转换为秒
        return time.strftime("%H:%M:%S", time.localtime(seconds))

    def generate_report(self):
        """生成传输报告"""
        if not self.packet_info:
            print("没有包发送，无法生成报告")
            return

        # 计算丢包率（重传包占总发送包的比例）
        total_packets_sent = sum(info['send_count'] for info in self.packet_info.values())
        total_retransmissions = total_packets_sent - len(self.packet_info)
        loss_rate = (total_retransmissions / total_packets_sent) * 100 if total_packets_sent >0 else 0

        # 计算RTT统计信息
        print("\n----- 传输接收报告 -----")
        print(f"应发送包数: {len(self.packet_info)}")
        print(f"实际发送总量: {total_packets_sent} (含{total_retransmissions}次重传)")
        print(f"丢包率: {loss_rate:.2f}%")

        # RTT统计（过滤掉异常值）
        if self.rtt_samples:
            df = pd.DataFrame(self.rtt_samples, columns=['RTT'])
            print(f"最大RTT: {df['RTT'].max():.2f}ms")
            print(f"最小RTT: {df['RTT'].min():.2f}ms")
            print(f"平均RTT: {df['RTT'].mean():.2f}ms")
            print(f"RTT标准差: {df['RTT'].std():.2f}ms")


def main():
    # 命令行参数: python udpclient.py <server_ip> <server_port> [loss_rate] [timeout]
    if len(sys.argv) < 3:
        print("命令: python/python3 udpclient.py <server_ip> <server_port> [loss_rate=0.3] [timeout=0.3]")
        return

    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    loss_rate = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
    timeout = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3

    # 生成测试数据 (50个包，每个包80字节)
    data = b''.join([f"PKT{i:02d}".encode() + b'x'*(80-5) for i in range(50)])
    # 包头标识：f"PKT{i:02d}".encode()，每个占5字节
    # 数据填充部分：b'x'*(80-5)

    client = GBNClient(server_ip, server_port, timeout, loss_rate)

    try:
        if client.connect():
            client.send_data(data)
    finally:
        # 确保线程正确关闭
        client.finish_event.set()
        if client.receiver_thread:
            client.receiver_thread.join(timeout=1.0)  # 等待1秒让线程退出


if __name__ == "__main__":
    main()
