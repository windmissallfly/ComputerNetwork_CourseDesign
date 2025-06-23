import socket
import struct
import threading


def handle_client(conn):
    try:
        # 接收Initialization
        header = conn.recv(6)
        ptype, N = struct.unpack('>HI', header)
        if ptype != 1:
            return
        conn.send(struct.pack('>H', 2))  # agree报文

        # 处理数据块
        for _ in range(N):
            header = conn.recv(6)
            ptype, data_len = struct.unpack('>HI', header)
            if ptype != 3:
                break
            data = conn.recv(data_len).decode('ascii')
            reversed_str = data[::-1]
            rev_bytes = reversed_str.encode('ascii')
            conn.send(struct.pack('>HI', 4, len(rev_bytes)) + rev_bytes)
    finally:
        conn.close()


def main():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(('0.0.0.0', 9000))
    server_sock.listen(5)
    while True:
        conn, addr = server_sock.accept()
        threading.Thread(target=handle_client, args=(conn,)).start()


if __name__ == "__main__":
    main()