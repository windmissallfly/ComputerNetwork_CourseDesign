task1由reversetcpclient.py和reversetcpserver.py组成，前者运行在windows11笔记本电脑上，后者运行在此笔记本电脑上的VMware虚拟机中。
宿主机上使用powershell和Pycharm2023.1.4运行python程序，python版本为3.119；虚拟机系统为Ubuntu20.04，python版本为3.8.10。
在宿主机上运行命令为python/python3 reversetcpclient.py <端口号> <Lmin> <Lmax>（server端默认9000端口号，输入其他端口号将不予连接）
在虚拟机上运行命令为python/python3 reversetcpserver.py