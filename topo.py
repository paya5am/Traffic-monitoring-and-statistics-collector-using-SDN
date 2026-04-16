from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel

def build_topology():
    net = Mininet(controller=RemoteController, switch=OVSKernelSwitch)  #new mininet instance
    
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)        #one controller
    s1 = net.addSwitch('s1', protocols='OpenFlow13')        #one switch
    
    h1 = net.addHost('h1', mac='00:00:00:00:00:01', ip='10.0.0.1/24')
    h2 = net.addHost('h2', mac='00:00:00:00:00:02', ip='10.0.0.2/24')
    h3 = net.addHost('h3', mac='00:00:00:00:00:03', ip='10.0.0.3/24')
    
    net.addLink(h1, s1)
    net.addLink(h2, s1) #connect hosts to switch
    net.addLink(h3, s1)
    
    net.build() #build network
    c0.start()  #start controller and attach to switch 
    s1.start([c0])
    
    CLI(net)
    net.stop()  #stop network

if __name__ == '__main__':
    setLogLevel('info')
    build_topology()
