#! /usr/bin/env python2.7
"""
    * Copyright (c) 2015 by Cisco Systems, Inc.
    * All rights reserved.
    
    Pathman init file
    
    Niklas Montin, 20140705, niklas@cisco.com
    

    odl_ip - ip address of odl controller
    odl_port -  port for odl rest on controller
    odl_user - username for odl rest access
    odl_password - password for odl rest access
    
    log_file - file to write log to - level INFO default
    log_size - max size of logfile before it rotates
    log_count - number of backup version of the log
    
    
    """

log_file = 'pathman.log'
log_size = 100000
log_count = 3
odl_port = '8181'
odl_user = 'admin'
odl_password = 'admin'
log_file = '/tmp/pathman.log'
odl_client_num = 1
odl_ip = '192.168.50.22%s' % str(odl_client_num - 1)
get_topo = 'http://%s:%s/restconf/operational/network-topology:network' \
           '-topology/topology/example-linkstate-topology-%s' % (odl_ip, odl_port, odl_client_num)
get_pcep = 'http://%s:%s/restconf/operational/network-topology:network' \
           '-topology/topology/pcep-topology-%s' %(odl_ip, odl_port, odl_client_num)