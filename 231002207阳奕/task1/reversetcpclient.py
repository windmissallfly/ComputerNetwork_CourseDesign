import socket
import struct
import random
import sys


def main():
    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    Lmin = int(sys.argv[3])
    Lmax = int(sys.argv[4])

    file_path = 'text.txt'

    # 读取文件并分块
    with open(file_path, 'r') as f:
        data = f.read()
    piece = []
    pos = 0
    file_len = len(data)
    while pos < file_len:
        pieces_len = random.randint(Lmin, Lmax) if (file_len - pos) > Lmax else (file_len - pos)
        piece.append(data[pos:pos + pieces_len])
        pos += pieces_len
    N = len(piece)

    # 连接服务器
    clientSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    clientSocket.connect((server_ip, server_port))

    # 发送Initialization报文

    # 在Python的struct.pack()函数中，'>HI'是格式字符串（format string），用于指定二进制数据的封装格式。
    # H表示2字节，I表示4字节
    # >标识了数据在内存中的排列顺序，会将数据存储为高位字节在前的模式
    # 一定不能修改>HI和下面的H！！！
    Type = 1
    clientSocket.send(struct.pack('>HI', Type, N))

    # 接收agree报文
    Type = struct.unpack('>H', clientSocket.recv(2))[0]
    if Type != 2:
        print("服务器无响应")
        return

    results = []
    for i, pieces in enumerate(piece):
        # 发送reverseRequest
        Type = 3
        pieces_bytes = pieces.encode('ascii')
        header = struct.pack('>HI', Type, len(pieces_bytes))
        clientSocket.send(header + pieces_bytes)

        # 接收reverseAnswer
        header = clientSocket.recv(6)
        Type, rev_len = struct.unpack('>HI', header)
        if Type != 4:
            print("服务器应答报文丢失")
            break
        reversed_data = clientSocket.recv(rev_len).decode('ascii')
        print(f"{i}:{reversed_data}")
        results.append(reversed_data)

    # 反转后字符串写入文件
    with open('reversed.txt', 'w') as f:
        f.write(''.join(results))
    clientSocket.close()


if __name__ == "__main__":
    main()