import socket
import struct
import random
import sys
import time
import threading

# 自定义协议首部格式
# I：4字节，B：1字节，Q：8字节，H：2字节
header_Format = ">IIBQH"  # 序列号(4字节) + 确认号(4字节) + 标志(1字节) + 时间戳(8字节) + 数据长度(2字节)
header_Size = struct.calcsize(header_Format)

# 标志位定义
flag_SYN = 0x1
flag_ACK = 0x2
flag_DATA = 0x4
flag_FIN = 0x8


class UDPServer:
    def __init__(self, port, loss_rate=0.3):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', port))
        self.loss_rate = loss_rate
        # 存储客户端状态: {addr: {'next_seq': int, 'server_seq': int}}
        self.connections = {}
        self.running = True

    def start(self):
        """启动UDP服务器"""
        print(f"服务器在{self.sock.getsockname()[1]}端口启动")

        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                # 启动线程处理客户端请求
                threading.Thread(target=self.handle_client, args=(data, addr)).start()
            except Exception as e:
                if self.running:
                    print(f"服务器异常: {e}")
                break

    def stop(self):
        """停止服务器"""
        self.running = False
        self.sock.close()

    def handle_client(self, data, addr):
        """处理客户端请求"""
        if len(data) < header_Size:
            return

        # 解析包头
        header = data[:header_Size]
        payload = data[header_Size:]
        seq, ack, flags, ts, data_len = struct.unpack(header_Format, header)
        payload = payload[:data_len]

        # 检查连接状态
        if addr not in self.connections:
            # 新连接
            self.connections[addr] = {
                'client_addr': addr,
                'next_seq': 0,
                'server_seq': random.randint(1, 1000),
                'connected': False
            }

        client_state = self.connections[addr]

        # 处理SYN标志
        if flags & flag_SYN:
            return self.handle_syn(addr, client_state, seq)

        # 处理数据包
        if flags & flag_DATA:
            return self.handle_data(addr, client_state, seq, payload)

        # 处理FIN标志
        if flags & flag_FIN:
            self.send_fin_ack(addr, client_state, seq)
            # 移除客户端状态
            if addr in self.connections:
                del self.connections[addr]

    def handle_syn(self, addr, client_state, seq):
        """处理SYN包"""
        if not client_state['connected']:
            # 第一次握手：回复SYN-ACK
            client_state['next_seq'] = seq + 1
            ack_num = client_state['next_seq']
            self.send_syn_ack(addr, client_state, ack_num)
            client_state['connected'] = True
            print(f"与 {addr} 建立连接")

    def send_syn_ack(self, addr, client_state, ack_num):
        """发送SYN-ACK包"""
        header = struct.pack(
            header_Format,
            client_state['server_seq'],
            ack_num,
            flag_SYN | flag_ACK,
            0,  # 时间戳
            0  # 数据长度
        )
        self.sock.sendto(header, addr)

    def handle_data(self, addr, client_state, seq, payload):
        """处理数据包"""
        # 模拟丢包
        if random.random() < self.loss_rate:
            print(f"丢包 {addr}, 第{seq}个 (模拟丢包)")
            return

        # 打印接收信息
        print(f"收到包 {addr}, 第{seq}个, 长度为 {len(payload)}")

        # 更新服务器序列号（对于累积确认）
        client_state['server_seq'] += 1

        # 累积确认
        ack_num = seq + 1
        client_state['next_seq'] = ack_num

        # 发送ACK
        self.send_ack(addr, client_state, ack_num)

    def send_ack(self, addr, client_state, ack_num):
        """发送ACK包"""
        time_stamp = int(time.time() * 1e6)
        header = struct.pack(
            header_Format,
            client_state['server_seq'],
            ack_num,
            flag_ACK,
            time_stamp,  # 时间戳
            0  # 数据长度
        )
        self.sock.sendto(header, addr)

    def send_fin_ack(self, addr, client_state, seq):
        """处理FIN并发送ACK"""
        ack_num = seq + 1
        header = struct.pack(
            header_Format,
            client_state['server_seq'],
            ack_num,
            flag_ACK,
            0,  # 时间戳
            0  # 数据长度
        )
        self.sock.sendto(header, addr)
        print(f"与 {addr} 关闭连接")


def main():
    # 命令行参数: python udpserver.py <port> [loss_rate]
    if len(sys.argv) < 2:
        print("正确命令: python/python3 udpserver.py <port> [loss_rate=0.3]")
        return

    port = int(sys.argv[1])
    loss_rate = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3

    server = UDPServer(port, loss_rate)

    try:
        server.start()
    except KeyboardInterrupt:
        print("停止服务器...")
        server.stop()


if __name__ == "__main__":
    main()
