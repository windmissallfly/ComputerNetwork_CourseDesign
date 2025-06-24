import socket
import struct
import threading


def handle_client(conn):
    try:
        header = conn.recv(6)
        Type, N = struct.unpack('>HI', header) # Initialization报文
        if Type != 1:
            return
        Type = 2
        conn.send(struct.pack('>H', Type))  # agree报文

        # 处理数据块
        for _ in range(N):
            header = conn.recv(6)
            Type, data_len = struct.unpack('>HI', header) # reverseRequest报文
            if Type != 3:
                break
            data = conn.recv(data_len).decode('ascii')
            reversed_str = data[::-1]
            rev_bytes = reversed_str.encode('ascii')
            Type = 4
            conn.send(struct.pack('>HI', Type, len(rev_bytes)) + rev_bytes) # reverseAnswer报文
    finally:
        conn.close()


def main():
    serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    serverSocket.bind(('0.0.0.0', 9000))
    serverSocket.listen(5)
    while True:
        conn, addr = serverSocket.accept()
        threading.Thread(target=handle_client, args=(conn,)).start()


if __name__ == "__main__":
    main()