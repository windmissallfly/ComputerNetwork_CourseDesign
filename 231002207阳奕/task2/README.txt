task2由udpclient.py和udpserver.py组成，前者运行在windows11笔记本电脑上，后者运行在此笔记本电脑上的VMware虚拟机中。
宿主机上使用powershell和Pycharm2023.1.4运行python程序，python版本为3.119；虚拟机系统为Ubuntu20.04，python版本为3.8.10。
在宿主机上运行命令为python/python3 udpclient.py <server_ip> <server_port> [loss_rate=0.3] [timeout=0.3]（端口号可以自行指定，与tcp不同）
在虚拟机上运行命令为python/python3 udpserver.py <port> [loss_rate=0.3]