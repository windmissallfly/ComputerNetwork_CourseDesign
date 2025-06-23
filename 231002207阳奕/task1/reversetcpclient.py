import socket
import struct
import random
import sys


def main():
    # 解析命令行参数
    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    Lmin = int(sys.argv[3])
    Lmax = int(sys.argv[4])

    file_path = 'text.txt'

    # 读取文件并分块
    with open(file_path, 'r') as f:
        data = f.read()
    chunks = []
    pos = 0
    file_len = len(data)
    while pos < file_len:
        chunk_len = random.randint(Lmin, Lmax) if (file_len - pos) > Lmax else (file_len - pos)
        chunks.append(data[pos:pos + chunk_len])
        pos += chunk_len
    N = len(chunks)

    # 连接服务器
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((server_ip, server_port))

    # 发送Initialization报文
    sock.send(struct.pack('>HI', 1, N))

    # 接收agree报文
    if struct.unpack('>H', sock.recv(2))[0] != 2:
        print("协议错误")
        return

    results = []
    for i, chunk in enumerate(chunks):
        # 发送reverseRequest
        chunk_bytes = chunk.encode('ascii')
        header = struct.pack('>HI', 3, len(chunk_bytes))
        sock.send(header + chunk_bytes)

        # 接收reverseAnswer
        header = sock.recv(6)
        ptype, rev_len = struct.unpack('>HI', header)
        if ptype != 4:
            print("协议错误")
            break
        reversed_data = sock.recv(rev_len).decode('ascii')
        print(f"{i}:{reversed_data}")
        results.append(reversed_data)

    # 写入反转文件
    with open('reversed.txt', 'w') as f:
        f.write(''.join(results))
    sock.close()


if __name__ == "__main__":
    main()