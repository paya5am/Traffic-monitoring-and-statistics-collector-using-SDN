from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub
from operator import attrgetter

class TrafficMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(TrafficMonitor, self).__init__(*args, **kwargs)
        self.mac_to_port = {}                       #keeps track of mac addresses
        self.datapaths = {}                         #switch tracking
        self.monitor_thread = hub.spawn(self._monitor)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath      #add switch if active
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:           
                del self.datapaths[datapath.id]         #remove inactive swithc

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)                 #statistics requested from switch every 10 secs 
            hub.sleep(10)

    def _request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
        
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']      #new port from host

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst           #configure mac addresses
        src = eth.src
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})       #initialize mac table and map prts 
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:       #if port is known, forward data , else flood it 
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:      #if port is known set up flow rule and direct data into it  
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                self.add_flow(datapath, 1, match, actions, msg.buffer_id)
                return
            else:
                self.add_flow(datapath, 1, match, actions)

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def _flow_stats_reply_handler(self, ev):
        body = ev.msg.body
        self.logger.info('\n--- Flow Stats Report (DPID: %016x) ---', ev.msg.datapath.id)
        self.logger.info('InPort    EthSrc            EthDst            Packets   Bytes')
        self.logger.info('--------  ----------------  ----------------  --------  --------')
        for stat in sorted([flow for flow in body if flow.priority == 1],                       #only display known flows 
                           key=lambda flow: (flow.match.get('in_port'), flow.match.get('eth_dst'))):
            self.logger.info('%8x  %17s  %17s  %8d  %8d',
                             stat.match.get('in_port'), stat.match.get('eth_src'),
                             stat.match.get('eth_dst'), stat.packet_count, stat.byte_count)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body      #display portwise statistics 
        self.logger.info('\n--- Port Stats Report (DPID: %016x) ---', ev.msg.datapath.id)
        self.logger.info('PortNum   RxPackets RxBytes   TxPackets TxBytes')
        self.logger.info('--------  --------- --------  --------- --------')
        for stat in sorted(body, key=attrgetter('port_no')):
            self.logger.info('%8x  %9d %8d  %9d %8d',
                             stat.port_no, stat.rx_packets, stat.rx_bytes,
                             stat.tx_packets, stat.tx_bytes)
