#! /usr/bin/env python2.7
"""
    * Copyright (c) 2015 by Cisco Systems, Inc.
    * All rights reserved.

    Pathman

    Niklas Montin, 20140705, niklas@cisco.com

    -- Get the link-state topology and build a graph
    20141022, Niklas -  Fixed Helium support - removed the repeated key portion  'l3-unicast-igp-topology'
                        Could add a test to see what key to use.
    20141111, Niklas - Fixed one more Helium key-change path[path][0] and 'network-topology-pcep:' being repeated
    20141201, Niklas - ver3.5 - compacted the filestructure: rerst_server_v5, topo_data and pathman35
    20141202, Niklas - ver 4.0 - PCEP stateful 07 work, using xml
    20141203, Niklas - Adding rotating log
    20141204, Niklas - ver 4.1 Enhanced url error checking, nprint retired for python logging
    20141208, Niklas - ver 4.2 config_ini.py now holds relevant environmend variables (ODL ip-address and port)
    20141213, Niklas - ver 4.3 configfile instead of configdict
                        added 2sec delay after create of stateful 07 LSP
    20150303, Niklas - ver 4.4, merged 4.2 and 4.3 changes - sleep and error checking
    20150303, Niklas - ver 4.5, refresh topology when getTopo is send
    20150312, Wei    - ver 4.6, add prefix in node and traffic in link
    20150312, Niklas - ver 4.7, added support for 66 nodes in topo with GPS coordinates (topo_data.py)
    20150401, Wei - ver 4.7.1, fix bug for missing nodes
    20150407, Niklas - ver 4.7.2, minor bugfix for missing command status from 02LSP
    20150522, Niklas - ver 4.8, OSPF support, broadcast network support, namelookup for ospf
    20150531, Niklas - ver 4.9, pseudo node fixes
    20150830, Niklas - ver 4.9b - Lithium changes - auth and xml payload for create and delete
    20150930, Niklas - ver 5.0 - Minor cleanup for publishing
    """
__author__ = 'niklas'

import os, re, time, sys
import requests

import json
import logging
import logging.config
from logging.handlers import RotatingFileHandler
from logging import Formatter
from collections import namedtuple
from copy import deepcopy
from topo_data import topologyData

from pprint import pprint

import datetime as _datetime
from string import Template

#==============================================================
version = '5.0'
# Defaults overridden by pathman_ini.py

log_size = 100000
log_count = 3
#log_level = 'INFO'
log_level = 'DEBUG'

from pathman_ini import *
import netaddr
#==============================================================
Node = namedtuple('Node', ['name', 'id', 'loopback', 'portlist','pcc','pcep_type','prefix'])
LSP = namedtuple('LSP',['name', 'pcc', 'hoplist', 'iphoplist'])

create_lsp = 'http://%s:%s/restconf/operations/network-topology-pcep:add-lsp' %(odl_ip, odl_port)
update_lsp = 'http://%s:%s/restconf/operations/network-topology-pcep:update-lsp' %(odl_ip, odl_port)
delete_lsp = 'http://%s:%s/restconf/operations/network-topology-pcep:remove-lsp' %(odl_ip, odl_port)
get_topo = 'http://%s:%s/restconf/operational/network-topology:network' \
           '-topology/topology/%s' % (odl_ip, odl_port, bgp_topo_id)
get_pcep = 'http://%s:%s/restconf/operational/network-topology:network' \
           '-topology/topology/%s' % (odl_ip, odl_port, pcep_topo_id)
curl_cmd = 'curl -X POST -H Content-Type:application/json  -d '


topo_toplevel_parts = [u'node', u'topology-id', u'link', u'topology-types', u'server-provided']
pcep_toplevel_parts = ['topology']
pcep_topology_parts = ['topology-id', 'topology-types', 'node']

string = "bgpls://IsisLevel2:1/type=node&as=65504&domain=505290270&router=0000.0000.0029"

lsp07_xml = '''<input xmlns="urn:opendaylight:params:xml:ns:yang:topology:pcep">
    <node>{pcc}</node>
    <name>{name}</name>
    <arguments>
    <lsp xmlns="urn:opendaylight:params:xml:ns:yang:pcep:ietf:stateful">
    <delegate>true</delegate>
    <administrative>true</administrative>
    </lsp>
    <endpoints-obj>
    <ipv4>
    <source-ipv4-address>{src}</source-ipv4-address>
    <destination-ipv4-address>{dst}</destination-ipv4-address>
    </ipv4>
    </endpoints-obj>
    <ero>{ero}</ero>
    </arguments>
    <network-topology-ref xmlns:topo="urn:TBD:params:xml:ns:yang:network-topology">/topo:network-topology/topo:topology[topo:topology-id="{pcep_topo_id}"]</network-topology-ref>
    </input>'''

lspDelete_xml = '''<input xmlns="urn:opendaylight:params:xml:ns:yang:topology:pcep">
     <node>{pcc}</node>
     <name>{name}</name>
     <network-topology-ref xmlns:topo="urn:TBD:params:xml:ns:yang:network-topology">/topo:network-topology/topo:topology[topo:topology-id="{pcep_topo_id}"]</network-topology-ref>
    </input>'''


lsp07_xml_helium = '''<input>
    <node>{pcc}</node>
    <name>{name}</name>
    <arguments>
    <lsp xmlns:stateful="urn:opendaylight:params:xml:ns:yang:pcep:ietf:stateful">
    <delegate>true</delegate>
    <administrative>true</administrative>
    </lsp>
    <endpoints-obj>
    <ipv4>
    <source-ipv4-address>{src}</source-ipv4-address>
    <destination-ipv4-address>{dst}</destination-ipv4-address>
    </ipv4>
    </endpoints-obj>
    <ero>{ero}</ero>
    </arguments>
    <network-topology-ref xmlns:topo="urn:TBD:params:xml:ns:yang:network-topology">/topo:network-topology/topo:topology[topo:topology-id="{pcep_topo_id}"]</network-topology-ref>
    </input>'''

lsp07update_xml = '''<input>
    <node>{pcc}</node>
    <name>{name}</name>
    <arguments>
    <lsp xmlns:stateful="urn:opendaylight:params:xml:ns:yang:pcep:ietf:stateful">
    <delegate>true</delegate>
    <administrative>true</administrative>
    </lsp>
    <ero>{ero}</ero>
    </arguments>
    <network-topology-ref xmlns:topo="urn:TBD:params:xml:ns:yang:network-topology">/topo:network-topology/topo:topology[topo:topology-id="{pcep_topo_id}"]</network-topology-ref>
    </input>'''

ero_xml = '''<subobject>
    <loose>false</loose>
    <ip-prefix><ip-prefix>{hop}/32</ip-prefix></ip-prefix>
    </subobject>
    '''

class Puck():
    """ Name Node was taken,
        holds path information to neighbors,
        every node spawns of Pucks as their neighbors,
        not a one-to-one with nodes.
        """
    def __init__(self, id = '', end = '',pathlist = [], metriclist = [], topo = [], past = []):
        self.id = id
        self.end = end
        self.pathlist = pathlist
        self.metriclist = metriclist
        self.topo = topo
        self.pastlist = past

debug_modules = ['node_structure']

class debugFilter(logging.Filter):
    ''' limits debug output to selected modules '''
    def filter(self, record):
        if record.levelname != 'DEBUG':
            return True
        else:
            return  record.funcName in debug_modules

class MyFormatter(logging.Formatter):
    ''' Gives us a dot instead of a comma in the log printout '''
    converter = time.gmtime
    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            t = time.strftime("%Y-%m-%d %H:%M:%S", ct)
            s = "%s.%03d" % (t, record.msecs)
        return s

LOGGING = {
    'version': 1,
    'filters': {
        'module_filter': {
            '()': debugFilter
            }
        },
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
                },
        'to_screen': {
            'format': '[%(levelname)s] %(funcName)s: %(message)s'
            },
        'to_file':{
            '()':MyFormatter,
            'format' : '%(process)d %(asctime)12s UTC %(name)s:%(funcName)-12s %(levelname)s: %(message)s'
            }
        },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['module_filter'],
            'formatter':'to_screen'
            },
        'logtofile':{
            'class': 'logging.handlers.RotatingFileHandler',
            'filters': ['module_filter'],
            'formatter':'to_file',
            'filename': log_file,
            'maxBytes': log_size,
            'backupCount': log_count,
            'encoding': 'utf8'
            }
        },
    'root': {
        'level': log_level,
        'handlers': ['console','logtofile']
        #'handlers': ['logtofile']
        },
}


def name_check(address):
    '''check if a name is mapped to address'''
    import socket
    try:
        name = socket.gethostbyaddr(address)[0]
        return True, name
    except:
        return False, ""

def ipv4_in_network(ip, network):
    '''check if the ip is in the network'''
    def mask_check(num):
        ''' check bits in mask and how many octets we need to match'''
        oct = num /8
        bits = num % 8
        return oct, bits

    mask = network.split('/')[-1]
    net = network.split('/')[0]
    
    ip_oct = ip.split('.')
    net_oct = net.split('.')
    oct, bits = mask_check(int(mask))
    
    for i in range(oct):
        if ip_oct[i] != net_oct[i]:
            return False
    # Are you still here?
    if oct == 4 or bits == 0:
        return True
    
    ip_bin = bin(int(ip_oct[oct]))
    net_bin = bin(int(net_oct[oct]))
    if ip_bin[2:bits+2] == net_bin[2:bits+2]:
        return True
    else:
        return False


def get_url(url):
    '''request url'''
    headers = {'Content-type': 'application/json'}
    try:
        response =  requests.get(url, headers = headers, auth = (odl_user,odl_password), verify=False)
        logging.info("Url get Status: %s" % response.status_code)
        
        if response.status_code in [200]:
            return response.json()
        else:
            logging.info(str(response.text))
            return {}
    except requests.exceptions.ConnectionError, e:
        logging.error('Connection Error: %s' % e.message)
        return {}

def locations_of_substring(string,target, offset=0):
    '''recursive counter of all occurances'''
    temp = []
    start = string.find(target)
    
    if start != -1:
        temp = [start+offset]
        temp += locations_of_substring(string[start+len(target):],target, offset +start+len(target))
    return temp

def html_style(string):
    """ find arguments and build list of dicts """

    first = locations_of_substring(string,'/')
    start = locations_of_substring(string,'&')
    end = locations_of_substring(string,'=')
    start.insert(0,first[-1])

    return chop_chop(start,end,string)

def chop_chop(start, end, string):
    """ Build value pair dict from restconf response """

    mydict = {}
    while len(start)>0:

        arg = string[start[0]+1:end[0]]
        if len(start) > 1:
            inext = start[1]
        else:
            inext = len(string)
        value = string[end[0]+1:inext]

        mydict.update({arg:value})
        start.pop(0)
        end.pop(0)

    return mydict

def find_link2(local, remote, address):
    """ Determine what node is connected to which """
    for link_dict in link_list:
        if link_dict['local-router'] == local and link_dict['remote-router'] == remote:
            try:
                return link_dict[address]
            except:
                return -1
    return(-1)

def node_structure(my_topology, debug = 2):
    """ learn (print out) the topology structure """

    node_list = []
    pcc_list = get_pcep_type(debug)
    logging.debug("pcc_list: %s" % pcc_list)
    try:
        node_dictlist = my_topology['topology'][0]['node']
        if len(pcc_list) > 0:
            loops = [pnode['loopback'] for pnode in pcc_list]
        else:
            loops = []
        logging.debug("Loopbacks of nodes: %s" % loops)

    except:
        logging.info("We have no nodes in our BGP-LS topology")
        return [], []

    for nodes in my_topology['topology'][0]['node']:
        #try:
        node_dict = html_style(nodes['node-id'])
        #logging.debug("node_dict: %s" % node_dict)
        prefix_array = []
        if 'prefix' in nodes['l3-unicast-igp-topology:igp-node-attributes'].keys():
            for prefix in nodes['l3-unicast-igp-topology:igp-node-attributes']['prefix']:
                prefix_array.append(prefix['prefix'])
                #logging.debug("prefix: %s, metric: %s " % (prefix['prefix'],prefix['metric']))
        node_ports = []
        for link in nodes['termination-point']:
            #logging.debug("port: %s " % link['tp-id'])
            if 'tp-id' in link.keys():
                port_dict = html_style(link['tp-id'])
                if 'ipv4' in port_dict.keys():
                    node_ports.append(port_dict['ipv4'])
        index = -1
        router_id = ""
        name = ""
        pcc = ""
        pcep_type = ""
        for keys in nodes['l3-unicast-igp-topology:igp-node-attributes'].keys():
            if keys == 'router-id':
                if nodes['l3-unicast-igp-topology:igp-node-attributes']['router-id'][0] in loops:
                    router_id = nodes['l3-unicast-igp-topology:igp-node-attributes']['router-id'][0]
                    index = loops.index(router_id)
                    pcc = pcc_list[index]['pcc']
                    pcep_type = pcc_list[index]['pcep_type']
            elif keys == 'name':
                name = nodes['l3-unicast-igp-topology:igp-node-attributes']['name']
        if name == "":
            name = node_dict['router']
            if 'router-id' in nodes['l3-unicast-igp-topology:igp-node-attributes'].keys():
                success, hname = name_check(nodes['l3-unicast-igp-topology:igp-node-attributes']['router-id'][0])
                if success:
                    name = hname
        if name.isdigit():
            name = str(netaddr.IPAddress(int(name)))
        node = Node(name,node_dict['router'],router_id,node_ports,pcc, pcep_type, prefix_array)
        logging.info("New node: %s" % str(node))
        node_list.append(node)
    logging.info(node_list)
    return node_list
    
def pseudo_net_build(node_list):
    pseudo_net = []
    for node in node_list:
        if node.name == node.id:
            for owner in node_list:
                if owner.id == node.id[:len(owner.id)] and owner.name != node.name:
                    pseudo_network = '0.0.0.0/32'
                    for network in owner.prefix:
                        #logging.info("calling ipv4_in_network for: %s - owner:%s" %(node.name,owner.name))
                        if ipv4_in_network(node.portlist[0], network):
                            pseudo_network = network
                    node_list[node_list.index(node)] = node._replace(name= owner.name+node.id[len(owner.id):],pcep_type="pseudonode",prefix=pseudo_network)
                    pseudo_net += node.portlist
                    logging.info("Owner of Pseduo: %s is: %s" % (node.name, owner.name))
                    break
    logging.info(pseudo_net)
    return pseudo_net

def node_links(my_topology, debug = 2):
    """ Dumps link info """
    net = {}
    link_list = []
    #nprint2 (" Number of links: %s" % len(my_topology['topology'][0]['link']), debug)
    try:
        for link in my_topology['topology'][0]['link']:
            link_dict = html_style(link['link-id'])
            link_list.append(link_dict)
            if link_dict['local-router'] in net.keys():
                net[link_dict['local-router']].update({link_dict['remote-router']:link['l3-unicast-igp-topology:igp-link-attributes']['metric']})

            else:
                net.update({link_dict['local-router']:{link_dict['remote-router']:link['l3-unicast-igp-topology:igp-link-attributes']['metric']}})
            #nprint2 ("Link: %s" % link['link-id'], debug)
            #nprint2 ("Metric: %s" % link['l3-unicast-igp-topology:igp-link-attributes']['metric'], debug)
    except:
        logging.info("We have no links in our BGP-LS topology")
    return net, link_list

def copyTopo(node_dict, ref_nodelist):
    """ copy coordinates from ref topo """
    for node in ref_nodelist:
        if node_dict['name'] == node['name']:
            for key in ['latitude','longitude','type','icon','y','x']:
                node_dict[key] = node[key]

def pseudo_net_check(address):
    '''add pseduo node hop in hoplist'''
    addr = address.split('/')[0]
    for node in pseudo_list:
        #for prefix in node.prefix:
        if ipv4_in_network(addr, node.prefix):
            logging.info("Found: %s" % node.name)
            return True, node.name
    return False, ''

def list_pcep_lsp(node_list, debug):
    """ reads pcep db from netowrk and provies a list of lsp's """
    my_pcep = get_url(get_pcep)

    lsplist = []
    try:
        for node in my_pcep['topology'][0]['node']:
            pcc = node['network-topology-pcep:path-computation-client']['ip-address']
            if 'reported-lsp' in node['network-topology-pcep:path-computation-client'].keys():
                for path in node['network-topology-pcep:path-computation-client']['reported-lsp']:

                    name = path['name']
                    ip_hoplist = []
                    if 'odl-pcep-ietf-stateful07:lsp' in path['path'][0].keys():
                        if 'operational' in path['path'][0]['odl-pcep-ietf-stateful07:lsp'].keys():
                            if path['path'][0]['odl-pcep-ietf-stateful07:lsp']['operational'] == 'up':
                                for nexthop in path['path'][0]['ero']['subobject']:
                                    ip_hoplist.append(nexthop['ip-prefix']['ip-prefix'])
                                hoplist = []
                                originate = name_from_pcc(pcc, node_list, debug)
                                if originate != '':
                                    hoplist.append(originate)
                                for interface in ip_hoplist:
                                    temp = find_node(node_list, interface,debug)
                                    #if temp in pseudo_net:
                                    success, pname = pseudo_net_check(interface)
                                    if success:
                                        hoplist.append(pname)
                                    hoplist.append(temp)
                                my_lsp = LSP(name,pcc,hoplist,ip_hoplist)
                                lsplist.append(my_lsp)
    except:
        logging.info("We have no nodes in our PCEP Topology")
    return lsplist

def find_node(node_list, interface, debug):
    """ find which node and interface belongs to """
    for node in node_list:
        if "pseudonode" not in node:
            for port in node.portlist:
                if port == interface.split('/')[0]:
                    return node.name

def find_link(my_topology, local, remote, debug = 2):
    """ Determine what node is connected to which """
    for link in my_topology['topology'][0]['link']:
        link_dict = html_style(link['link-id'])
        if link_dict['local-router'] == local and link_dict['remote-router'] == remote:
            try:
                return link_dict['ipv4-neigh']
            except:
                return -1
    return(-1)

def map_name2node(node_list, name):
    """ find node id from name """
    for node in node_list:
        if name == node.name:
            return node.id

    return '0000.0000.0000'

def map_node2name(node_list, node_id):
    """ find name from node-id """
    for node in node_list:
        if node_id == node.id:
            return node.name

    return "none"

def reduce_topo(topo, begone):
    """ Remove node from topo """

    new_topo = deepcopy(topo)

    for nodes in new_topo:
        if begone in new_topo[nodes]:
            del new_topo[nodes][begone]

    del new_topo[begone]

    return new_topo


def nikstra(this_node):
    """ find all paths between start and end) """

    if this_node.id == this_node.end:
        return

    else:

        nbor_list = []
        new_topo = reduce_topo(this_node.topo, this_node.id)
        for neighbor in this_node.topo[this_node.id]:
            if neighbor == this_node.end:
                this_node.pathlist.append([this_node.id,this_node.end])
                this_node.metriclist.append(this_node.topo[this_node.id][this_node.end])

            else:
                # full init required here - due to python feature :)
                nbor = Puck()
                nbor.id = neighbor
                nbor.end = this_node.end
                nbor.pathlist = []
                nbor.metriclist = []
                nbor.pastlist = []
                nbor.pastlist.append(this_node.id)
                nbor.topo = deepcopy(new_topo)
                nbor_list.append(nbor)

                nikstra(nbor)

                for path in nbor.pathlist:
                    path.insert(0,this_node.id)

                for i in range(len(nbor.metriclist)):
                    nbor.metriclist[i] = nbor.metriclist[i] + this_node.topo[this_node.id][nbor.id]

        for nbor in nbor_list:

            for path in nbor.pathlist:
                if path != []:
                    this_node.pathlist.append(path)
            for i in range(len(nbor.metriclist)):
                 this_node.metriclist.append(nbor.metriclist[i])

        return


def translate_pathnames(pathlist, debug):
    """ Insert nodenames in pathlist """
    npathlist = []

    for path in pathlist:

        npath = []
        for nodeid in path:
            npath.append(map_node2name(node_list, nodeid))
        npathlist.append(npath)

    return npathlist

def translate_pathids(path, debug):
    """ Insert nodeids in pathlist """

    npath = []
    for nodename in path:
        npath.append(map_name2node(node_list, nodename))

    return npath

def hop_not_source(linklist, hop):
    """ make sure hop is not a source """
    for links in linklist:
        if links['source'] == hop:
            return False
    return True

def translate_topo(node_list, net, debug):
    """ returns net topology in names """
    name_net = {}
    for nodeid in net.keys():
        name_hops = {}
        for hopid in net[nodeid]:
            name_hops.update({map_node2name(node_list, hopid):net[nodeid][hopid]})
        name_net.update({map_node2name(node_list, nodeid):name_hops})

    return name_net

def get_pcep_type(debug):
    '''update our node_list have pcep info'''
    my_pcep = get_url(get_pcep)

    pcc_list = []
    try:
        for node in my_pcep['topology'][0]['node']:
            loopback = node['network-topology-pcep:path-computation-client']['ip-address']
            pcc = node['node-id']
            if 'odl-pcep-ietf-stateful07:stateful' in node['network-topology-pcep:path-computation-client']['stateful-tlv'].keys():
                pcep_type = '07'
            else:
                pcep_type = '02'
            pcc_list.append({'pcc':pcc, 'loopback':loopback,'pcep_type':pcep_type} )
    except:
        logging.info("We have no nodes in our PCEP Topology")
    return pcc_list


def lsp_create_json(src, dst, name_of_lsp , pcc, debug):
    """ build a json structure to create LSPs """
    lsp_dict = {}
    lsp_dict.update({"input":{}})
    lsp_dict["input"].update({"node":pcc,
                             "name": name_of_lsp,
                             "network-topology-ref":'/network-topology:network-topology/network-topology:topology[network-topology:topology-id=\"%s\"]' % (pcep_topo_id),
                             "arguments":{}
                              })
    lsp_dict["input"]["arguments"] = {"endpoints-obj":{"ipv4":{"source-ipv4-address":src, "destination-ipv4-address": dst}}}
    return lsp_dict

def lsp_create_xml_07(src, dst, name_of_lsp , pcc, hoplist, debug):
    """ build a xml structure to create LSPs """
    hop_xml_list = []

    for hop in hoplist:
        step = {"hop":hop}
        new_xml = ero_xml.format(**step)
        hop_xml_list.append(new_xml)


    ero = "".join(hop_xml_list)
    new_lsp = {"pcc":pcc,
               "name":name_of_lsp,
               "src":src,
               "dst":dst,
               "ero":ero,
               "pcep_topo_id": pcep_topo_id}
    new_lsp_xml07 = lsp07_xml.format(**new_lsp)
    return new_lsp_xml07

def lsp_update_xml_07(src, dst, name_of_lsp , pcc, hoplist, debug):
    """ build a xml structure to update a LSPs """
    hop_xml_list = []

    for hop in hoplist:
        step = {"hop":hop}
        new_xml = ero_xml.format(**step)
        hop_xml_list.append(new_xml)


    ero = "".join(hop_xml_list)
    new_lsp = {"pcc":pcc,
               "name":name_of_lsp,
               "src":src,
               "dst":dst,
               "ero":ero,
               "pcep_topo_id":pcep_topo_id}
    lsp_update_xml07 = lsp07update_xml.format(**new_lsp)
    return lsp_update_xml07

def lsp_delete_json(name_of_lsp, pcc, debug):
    """ build a json strtucture for lsp delete """
    
    lsp_dict = {}
    lsp_dict.update({"input":{}})
    lsp_dict["input"].update({"node":pcc,
                             "name": name_of_lsp,
                             "network-topology-ref":'/network-topology:network-topology/network-topology:topology[network-topology:topology-id=\"%s\"]' % (pcep_topo_id)
                              })
    return lsp_dict
def lsp_delete_xml(name_of_lsp, pcc, debug):
    """ build a json strtucture for lsp delete """
    my_lsp = {'name':name_of_lsp,
              'pcc':pcc,
              "pcep_topo_id": pcep_topo_id}
    data = lspDelete_xml.format(**my_lsp)
    return data

def lsp_update_json(lsp_dict, path):
    """ build json structure for lsp path updates """

    path_dict = {}
    path_dict.update({"input":{}})
    path_dict["input"].update({"node":lsp_dict["input"]["node"],
                              "name":lsp_dict["input"]["name"],
                              "network-topology-ref":lsp_dict["input"]["network-topology-ref"],
                              "arguments":{}
                              })
    path_dict["input"]["arguments"] = { "operational":"true",
                                        "ero":{}
                                        }
    if path >0:

        explicit = []
        for hop in path:
            entry = {"loose": "false", "ip-prefix":{"ip-prefix":hop+"/32"}}
            explicit.append(entry)
        path_dict["input"]["arguments"]["ero"] = {"subobject":explicit}

    return path_dict

def build_odl_topology(debug):
    """Build and inilaize our data structures """
    global net
    global pseudo_net
    global pseudo_list
    global node_list
    global link_list
    global my_topology
    try:
        my_topology = get_url(get_topo)

        node_list = node_structure(my_topology, debug)
        pseudo_net = pseudo_net_build(node_list)
        pseudo_list = [ node for node in node_list if node.pcep_type == 'pseudonode']
        net, link_list = node_links(my_topology, debug)
        return True, 'all is well', len(net.keys())

    except :
        e = sys.exc_info()[0]
        logging.error(str(e))
        net = {}
        node_list = []
        my_topology = {}
        pseudo_net = pseudo_list = []
        return False, 'could not reach odl-server?', 0

def sort_paths(pathlist, metriclist, type):
    """ lets sort the pathlist """

    if type == 'igp':
        newpathlist = [path for (metric,path) in sorted(zip(metriclist,pathlist), key=lambda pair: pair[0])]
        newmetriclist = deepcopy(metriclist)
        newmetriclist.sort()
    else:
        newpathlist = deepcopy(pathlist)
        newpathlist.sort(lambda x,y: cmp(len(x), len(y)))
        newmetriclist = []
        for path in newpathlist:
            newmetriclist.append(len(path))
    return newpathlist, newmetriclist

def postUrl(url, data):
    import requests
    response = requests.get(url, data=data, auth = (odl_user, odl_password),headers= {'Content-Type': 'application/json'})
    print response.text
    return response.json()

def postXml(url, data):
    """ post our lsp creation commands """
    import requests
    logging.info("Resuest: '%s'", url)
    logging.info("Resuest: '\n%s'", data)
    response = requests.post(url, data=data, auth = (odl_user, odl_password),headers= {'Content-Type': 'application/xml'})
    print response.text
    #f = urllib2.urlopen(req)
    #response = f.read()
    #f.close()
    return response.json()

def getPathlist(dict_subcommand,debug):
    """ called from REST Server
        - build path list for given command """
    startname = dict_subcommand['src']
    stopname = dict_subcommand['dst']
    metrictype = dict_subcommand['metric']

    startid = map_name2node(node_list, startname)
    stopid = map_name2node(node_list, stopname)

    if startid == '0000.0000.0000' or stopid == '0000.0000.0000':
        return False, 'no such node', []

    dut = Puck(id=startid, end=stopid, topo = net)
    dut.pathlist = []
    dut.metriclist = []

    nikstra(dut)
    pathlist = translate_pathnames(dut.pathlist, debug)
    #metriclist = deepcopy(dut.metriclist)
    newpathlist, newmetriclist = sort_paths(pathlist, dut.metriclist,metrictype)

    return (True, 'we are good', newpathlist, newmetriclist)

def getHoplist(dict_subcommand,debug):
    """ called from REST Server
        - build hop list for given command """
    path = translate_pathids(dict_subcommand['path'],debug)
    logging.info("Path: %s" % path)
    hoplist = []
    j = 0
    while j < len(path)-1:
        temp = find_link2(path[j], path[j+1],'ipv4-neigh')
        if temp in pseudo_net:
            temp = find_link2(path[j+2], path[j+1],'ipv4-iface')
            j += 1
        j += 1
        hoplist.append(temp)
    logging.info("Hoplist: %s" % hoplist)
    if -1 in hoplist:
        return False, 'no link found',  hoplist
    return True, 'we are good', hoplist

def getHoplistOld(dict_subcommand,debug):
    """ called from REST Server
        - build hop list for given command """

    path = translate_pathids(dict_subcommand['path'],debug)
    logging.info("Path: %s" % path)

    hoplist = []
    for i in range(len(path)-1):
        temp = find_link(my_topology, path[i], path[i+1])
        if temp == -1:
            temp = find_link(my_topology, path[i+1], path[i])
        hoplist.append(temp)
    logging.info("Hoplist: %s" % hoplist)
    if -1 in hoplist:
        return False, 'no link found',  hoplist

    return True, 'we are good', hoplist

def create_02_Lsp(start_loopback, stop_loopback, lsp_name, pcc, hoplist, debug):
    ''' create 02 lsp '''
    my_new_lsp = lsp_create_json(start_loopback, stop_loopback, lsp_name, pcc, debug)
    my_new_path = lsp_update_json(my_new_lsp, hoplist)

    dict_reply = postUrl(create_lsp, json.dumps(my_new_lsp))
    logging.info("Create 02LSP response: %s" % dict_reply)

    if dict_reply['output'] == {}:
        dict_reply2 = postUrl(update_lsp, json.dumps(my_new_path))
        logging.info("Update Path response: %s" % dict_reply2)
        if  dict_reply2['output'] == {}:

            return True, 'Yes, we did it'
        else:
            success = False
            cause = dict_reply2['output']
    else:
        success = False
        cause = dict_reply['output']
    return success, cause

def createLsp(dict_subcommand,debug):
    """ called from REST Server
        - Create a LSP along the given path """
    path = dict_subcommand['path']
    lsp_name = dict_subcommand['name']
    success, cause, hoplist = getHoplist(dict_subcommand,debug)
    if success:
        startid = map_name2node(node_list, path[0])
        stopid = map_name2node(node_list, path[-1])
        for node in node_list:
            if startid == node.id:
                #pcc = node.loopback
                pcc = node.pcc
                pcep_type = node.pcep_type
                start_loopback = node.loopback
            if stopid == node.id:
                stop_loopback = node.loopback

        if pcep_type == '07':
            my_xml07 = lsp_create_xml_07(start_loopback, stop_loopback, lsp_name, pcc, hoplist, debug)
            dict_reply = postXml(create_lsp, my_xml07)
            logging.info("Create 07LSP response: %s" % dict_reply)
            #
            # Delay to overcome write/read issue in ODL
            # - should be removed once fixed
            time.sleep(2)

            if dict_reply['output'] == {}:
                return True, 'Yes, we did it'
            else:
                success = False
                cause = dict_reply['output']
        else:
            success, cause = create_02_Lsp(start_loopback, stop_loopback, lsp_name, pcc, hoplist, debug)

    return success, cause


def deleteLsp_old(dict_subcommand,debug):
    """ called from REST Server
        - Deleta a LSP by name  """

    lsp_name = dict_subcommand['name']

    startid = map_name2node(node_list, dict_subcommand['node'])
    pcc = ''
    for node in node_list:
        if startid == node.id:
            pcc = node.loopback

    if len(pcc) >0 :
        remove_my_lsp = lsp_delete_json(lsp_name,'pcc://'+pcc, debug)
        dict_reply = postUrl(delete_lsp, json.dumps(remove_my_lsp))
        logging.info("Delete LSP response: %s" % dict_reply)
        if dict_reply['output'] == {}:

            return True, 'Yes, we did it'

        else:
            success = False
            cause = dict_reply['output']
    return False, 'no pcc found'

def deleteLsp(dict_subcommand,debug):
    """ called from REST Server
        - Deleta a LSP by name  """

    lsp_name = dict_subcommand['name']

    startid = map_name2node(node_list, dict_subcommand['node'])
    pcc = ''
    for node in node_list:
        if startid == node.id:
            pcc = node.loopback

    if len(pcc) >0 :
        data = lsp_delete_xml(lsp_name,'pcc://'+pcc, debug)
        dict_reply = postXml(delete_lsp, data)
        logging.info("Delete LSP response: %s" % dict_reply)
        if dict_reply['output'] == {}:

            return True, 'Yes, we did it'

        else:
            success = False
            cause = dict_reply['output']
    return False, 'no pcc found'

def name_from_pcc(pcc, node_list, debug):
    """ return name as strin for pcc """
    for node in node_list:
        if node.loopback == pcc:
            return node.name
    return ''

def deleteAll(dict_subcommand, debug):
    """ delete all LSPs in the network """
    lsplist = list_pcep_lsp(node_list, debug)
    agg_success = True
    num_deleted = 0
    for lsp in lsplist:
        dict_subcommand = {'node': name_from_pcc(lsp.pcc, node_list, debug), 'name': lsp.name }
        success, cause = deleteLsp(dict_subcommand,debug)
        logging.info("Result: %s, name: %s" % (success, lsp.name))
        if success:
            num_deleted += 1
        agg_success &= success

    return agg_success, num_deleted


def listAllLsp(dict_subcommand, debug):
    """ called from REST Server
        - mostly a wrapper and dict translation """
    lsplist = list_pcep_lsp(node_list, debug)

    lspdictlist = []

    for lsp in lsplist:
        lsp_dict = {}
        lsp_dict.update({'name':lsp.name})
        lsp_dict.update({'pcc':lsp.pcc})
        lsp_dict.update({'path':lsp.hoplist})
        lsp_dict.update({'hops':lsp.iphoplist})
        lspdictlist.append(lsp_dict)

    logging.info("list: %s, formatted: %s" %(lsplist,lspdictlist))

    if len(lsplist) >0:
        return True, 'homerun', lspdictlist
    else:
        return True, 'no lsp found', []

def listNodeLsp(dict_subcommand, debug):
    """ called from REST Server
        - Which LSPs go through this node? """
    node = dict_subcommand['node']
    new_dict_list = []
    (success, status, lspdictlist) = listAllLsp(dict_subcommand, debug)
    if lspdictlist != []:
        for lspdict in lspdictlist:
            if node in lspdict['path']:
                new_dict_list.append(lspdict)

        return True, 'we did good', new_dict_list
    else:
        return success, status, new_dict_list

def topoCheck(temp_nodelist):
    ''' Fill in the blanks for up to 16 nodes '''
    network_name_list = [node['name'] for node in temp_nodelist]
    ref_name_list = [topologyData['nodes'][i]['name'] for i in range(len(topologyData['nodes']))]
    available_set = set(ref_name_list) - set(ref_name_list).intersection(set(network_name_list))
    unassigned_set = set(network_name_list) - set(network_name_list).intersection(set(ref_name_list))

    logging.info("Nodes not in topo_data.py: %s" % unassigned_set)
    logging.info("Nodes not used: %s" % available_set)

    i = 0
    temp_dict = {}
    for name in unassigned_set:
        #print list(available_set)
        mylist = list(available_set)

        logging.info("node: %s"% topologyData['nodes'][ref_name_list.index(mylist[i])])
        for key in ['latitude','longitude','type','icon','y','x']:
            temp_nodelist[network_name_list.index(name)][key] = topologyData['nodes'][ref_name_list.index(mylist[i])][key]

        i +=1

    return temp_nodelist



def getTopo(dict_subcommand, debug):
    """ called from REST Server
        - Get UI a topo to work with """
    #topo_response = {'nodes':[],'links':[]}
    success, cause, num_nodes = build_odl_topology(debug)
    if success:
        temp_nodelist = []

        for node in node_list:
            node_dict = {'name':node.name, 'site':node.name, 'ipaddress':node.loopback,'prefix':node.prefix}
            copyTopo(node_dict, topologyData['nodes'])
            temp_nodelist.append(node_dict)
            #topo_response['nodes'].append(node_dict)

        temp_nodelist = topoCheck(temp_nodelist)

        sorted_nodelist = sorted(temp_nodelist, key=lambda k: k['name'])
        topo_response = {'nodes':sorted_nodelist,'links':[]}
        net_by_name =translate_topo(node_list, net, debug)

        for node in net_by_name.keys():

            for hop in net_by_name[node].keys():
                if hop_not_source(topo_response['links'], hop):
                    #link_dict.update({'source':node, 'target':hop})
                    link_dict = {'source':None, 'target':None,'sourceTraffic':0, 'targetTraffic':0}
                    link_dict["source"]=node
                    link_dict["target"]=hop
                    link_dict["sourceTraffic"] = net_by_name[node][hop]
                    link_dict["targetTraffic"] = net_by_name[hop][node]
                    topo_response['links'].append(link_dict)

        logging.info("Topo build with %s nodes" % num_nodes)
        return True, 'another sunny day', topo_response
    else:
        logging.info("Failed to get topo: %s" % cause)
        return False, cause, []


def rest_interface_parser(list_subcommands, debug):
    """ interface module for rest API
        buld to handle stacked commands """
    response_list = []
    try:

        for dict_subcommand in list_subcommands:
            #nprint("Commands Recieved: %s" % dict_subcommand, debug=debug)
            logging.info("Commands Recieved: %s" % dict_subcommand)
            if 'path' == dict_subcommand['option']:
                Success, Cause, Pathlist, Metriclist = getPathlist(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                            'success':Success,
                            'path': Pathlist,
                            'metric': Metriclist
                            }

            elif 'hops' == dict_subcommand['option']:
                Success, Cause, Hoplist = getHoplist(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                            'success':Success,
                            'hops': Hoplist
                            }

            elif 'create' == dict_subcommand['option']:
                Success, Cause = createLsp(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                            'success':Success,
                            'name':dict_subcommand['name']
                            }

            elif 'delete' == dict_subcommand['option']:
                Success, Cause = deleteLsp(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                            'success':Success,
                            'name':dict_subcommand['name']
                            }
            elif 'delete_all' == dict_subcommand['option']:
                Success, num_deleted = deleteAll(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                        'success':Success,
                        'num_deleted' : num_deleted
                        }

            elif 'list_all' == dict_subcommand['option']:
                Success, Cause, lsplist = listAllLsp(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                            'success':Success,
                            'list':lsplist
                            }

            elif 'topo' == dict_subcommand['option']:
                Success, Cause, topo_dict = getTopo(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                            'success':Success,
                            'topology':topo_dict
                            }

            elif 'list_local' == dict_subcommand['option']:
                Success, Cause, lsplist = listNodeLsp(dict_subcommand,debug=debug)
                if Success:
                    temp = {'option': dict_subcommand['option'],
                            'success':Success,
                            'list':lsplist
                            }
            elif 'version' == dict_subcommand['option']:
                Success = True
                temp = {'option': dict_subcommand['option'],
                        'success':Success,
                        'version' : version
                        }
            elif 'refresh' == dict_subcommand['option']:
                Success, Cause, num_nodes = build_odl_topology(debug=debug)
                temp = {'option': dict_subcommand['option'],
                        'success':Success,
                        'num_nodes': num_nodes
                        }
            else:
                Success = False
                Cause = 'option error'

            if not Success:
                temp = {'option': dict_subcommand['option'],
                        'success':Success,
                        'cause': Cause
                        }

            response_list.append(temp)

    except ValueError:
        response_list = [{'option': dict_subcommand['option'],
                         'success': False,
                         'cause': 'value error'
                         }]

    return response_list

if __name__ == '__main__':
    """ Testing Area without REST frontend """

    debug = 1
    total = len(sys.argv)
    cmdargs = str(sys.argv)

    if 'debug' in cmdargs:
        debug = 1

    if 'debug2' in cmdargs:
        debug = 2

#    logger = create_rotating_log('Pathman',log_file)
#    logger.propagate = True
    #nprint('This is initializing the log',1)
    #logging.config.dictConfig(LOGGING)
    logging.config.fileConfig("pathman_logging.conf")
    logging.info('//This is initializing the log')
    logging.info("//Python version is %s.%s.%s" % sys.version_info[:3])
    logging.info("//Program is %s" % sys.argv[0])
    logging.info("//Current Directory is %s" % os.path.dirname(os.path.realpath(__file__)))


    my_topology = get_url(get_topo)
    node_list = node_structure(my_topology, debug)
    pseudo_net = pseudo_net_build(node_list)
    pseudo_list = [ node for node in node_list if node.pcep_type == 'pseudonode']
    net, link_list = node_links(my_topology, debug)

    my_pcep = get_url(get_pcep)
    logging.info("hej")
    lsplist = list_pcep_lsp(node_list, debug)

    (success, status, lspdictlist) = listNodeLsp({'node':'sjc'}, debug)
    print "List Node List",success, status, lspdictlist

    my_dict = lsp_create_xml_07('30.30.30.30', '22.22.22.22', 'niklas07' , '30.30.30.30', ['49.0.0.22'], 1)
    print my_dict

# bye bye
