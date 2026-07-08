#!/usr/bin/env python3
"""
Network Simulation Tool for AI Agents
A Flask-based REST API server for simulating network outages and providing
state management for AI agent interactions.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import uuid
import json
from datetime import datetime
import os
import traceback
import logging
from logging.handlers import RotatingFileHandler
import xml.etree.ElementTree as ET
from werkzeug.utils import secure_filename
import yaml

app = Flask(__name__)
CORS(app)

# Configure logging with rotating file handler
def setup_logging():
    """Configure logging with rotating file handler"""
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    root_logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        fmt='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Rotating file handler for detailed logs
    file_handler = RotatingFileHandler(
        filename=os.path.join(logs_dir, 'network_simulation.log'),
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    
    # Rotating file handler for errors only
    error_handler = RotatingFileHandler(
        filename=os.path.join(logs_dir, 'network_simulation_errors.log'),
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    
    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    
    # Configure Flask's werkzeug logger
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.WARNING)  # Reduce Flask request logging noise
    
    # Configure application logger
    app_logger = logging.getLogger(__name__)
    app_logger.setLevel(logging.DEBUG)
    
    # Log startup message
    app_logger.info("Logging system initialized with rotating file handlers")
    app_logger.info(f"Log files location: {logs_dir}")
    
    return app_logger

# Setup logging and get logger
logger = setup_logging()

# In-memory storage for network state
network_state = {
    'id': str(uuid.uuid4()),
    'timestamp': datetime.now().isoformat(),
    'topology': {
        'switches': []
    },
    'issues': [],
    'totalPorts': 24,
    'activePorts': 24,
    'faultyPorts': 0
}

def initialize_network():
    """Initialize the network topology with default values including connections and hosts"""
    global network_state
    
    # Define switch types and their roles in the data center
    switch_configs = [
        {
            'id': 'core-sw-1',
            'name': 'Core Switch 1',
            'location': 'Core Network - Rack A1',
            'model': 'Cisco Nexus 9364C',
            'type': 'core',
            'port_count': 12,
            'management_ip': '192.168.100.10'
        },
        {
            'id': 'agg-sw-1',
            'name': 'Aggregation Switch 1',
            'location': 'Aggregation Layer - Rack B1',
            'model': 'Cisco Catalyst 9300-48P',
            'type': 'aggregation',
            'port_count': 16,
            'management_ip': '192.168.100.20'
        },
        {
            'id': 'access-sw-1',
            'name': 'Access Switch 1',
            'location': 'Access Layer - Rack C1',
            'model': 'Cisco Catalyst 9200-24P',
            'type': 'access',
            'port_count': 24,
            'management_ip': '192.168.100.30'
        }
    ]
    
    switches = []
    connections = []
    hosts = []
    
    # Create switches with ports
    for switch_config in switch_configs:
        ports = []
        for port_index in range(switch_config['port_count']):
            # Define port types based on switch type and port number
            if switch_config['type'] == 'core':
                # Core switch ports - high capacity uplinks
                port_type = 'uplink' if port_index < 4 else 'trunk'
                required_sfp_type = 'QSFP28' if port_index < 4 else 'SFP28'
                capacity_gbps = 100 if port_index < 4 else 25
            elif switch_config['type'] == 'aggregation':
                # Aggregation switch - mix of uplinks and downlinks
                if port_index < 2:
                    port_type = 'uplink'
                    required_sfp_type = 'SFP28'
                    capacity_gbps = 25
                elif port_index < 8:
                    port_type = 'trunk'
                    required_sfp_type = 'SFP+'
                    capacity_gbps = 10
                else:
                    port_type = 'access'
                    required_sfp_type = 'SFP'
                    capacity_gbps = 1
            else:  # access switch
                # Access switch - mostly host connections
                if port_index < 2:
                    port_type = 'uplink'
                    required_sfp_type = 'SFP+'
                    capacity_gbps = 10
                else:
                    port_type = 'access'
                    required_sfp_type = 'RJ45'
                    capacity_gbps = 1
            
            port = {
                'id': f'{switch_config["id"]}-port-{port_index}',
                'switchId': switch_config['id'],
                'portNumber': port_index + 1,
                'portType': port_type,
                'status': 'CONNECTED',
                'sfpType': required_sfp_type,
                'sfpStatus': 'correct',
                'requiredSfpType': required_sfp_type,
                'capacityGbps': capacity_gbps,
                'utilization': 0,  # Current utilization percentage
                'connectedTo': None,  # Will be filled by connections
                'vlan': 'default',
                'description': f'{port_type.title()} Port {port_index + 1}',
                'lastUpdated': datetime.now().isoformat()
            }
            ports.append(port)
        
        switch = {
            'id': switch_config['id'],
            'name': switch_config['name'],
            'location': switch_config['location'],
            'model': switch_config['model'],
            'type': switch_config['type'],
            'managementIp': switch_config['management_ip'],
            'uptime': '45 days, 12:34:56',
            'cpu': 15,  # CPU utilization percentage
            'memory': 32,  # Memory utilization percentage
            'temperature': 45,  # Temperature in Celsius
            'ports': ports
        }
        switches.append(switch)
    
    # Define network connections between switches
    network_connections = [
        # Core to Aggregation connections
        {
            'id': 'conn-1',
            'sourceSwitch': 'core-sw-1',
            'sourcePort': 1,
            'targetSwitch': 'agg-sw-1',
            'targetPort': 1,
            'cableType': 'fiber',
            'cableLength': '15m',
            'protocol': 'ethernet',
            'status': 'active'
        },
        {
            'id': 'conn-2',
            'sourceSwitch': 'core-sw-1',
            'sourcePort': 2,
            'targetSwitch': 'agg-sw-1',
            'targetPort': 2,
            'cableType': 'fiber',
            'cableLength': '15m',
            'protocol': 'ethernet',
            'status': 'active'
        },
        # Aggregation to Access connections
        {
            'id': 'conn-3',
            'sourceSwitch': 'agg-sw-1',
            'sourcePort': 3,
            'targetSwitch': 'access-sw-1',
            'targetPort': 1,
            'cableType': 'fiber',
            'cableLength': '25m',
            'protocol': 'ethernet',
            'status': 'active'
        },
        {
            'id': 'conn-4',
            'sourceSwitch': 'agg-sw-1',
            'sourcePort': 4,
            'targetSwitch': 'access-sw-1',
            'targetPort': 2,
            'cableType': 'fiber',
            'cableLength': '25m',
            'protocol': 'ethernet',
            'status': 'active'
        }
    ]
    
    # Apply connections to port data
    for connection in network_connections:
        # Update source port
        for switch in switches:
            if switch['id'] == connection['sourceSwitch']:
                for port in switch['ports']:
                    if port['portNumber'] == connection['sourcePort']:
                        port['connectedTo'] = {
                            'type': 'switch',
                            'switchId': connection['targetSwitch'],
                            'portNumber': connection['targetPort'],
                            'connectionId': connection['id']
                        }
                        port['status'] = 'CONNECTED'
                        port['utilization'] = 25  # Sample utilization
        
        # Update target port
        for switch in switches:
            if switch['id'] == connection['targetSwitch']:
                for port in switch['ports']:
                    if port['portNumber'] == connection['targetPort']:
                        port['connectedTo'] = {
                            'type': 'switch',
                            'switchId': connection['sourceSwitch'],
                            'portNumber': connection['sourcePort'],
                            'connectionId': connection['id']
                        }
                        port['status'] = 'CONNECTED'
                        port['utilization'] = 25  # Sample utilization
    
    # Define connected hosts/servers
    connected_hosts = [
        {
            'id': 'web-server-1',
            'name': 'Web Server 1',
            'type': 'server',
            'ip': '10.1.1.10',
            'mac': '00:1B:44:11:3A:B7',
            'switchId': 'access-sw-1',
            'portNumber': 3,
            'vlan': 'web-servers',
            'status': 'active',
            'os': 'Ubuntu 22.04 LTS',
            'services': ['nginx', 'mysql'],
            'location': 'Server Room A'
        },
        {
            'id': 'db-server-1',
            'name': 'Database Server 1',
            'type': 'server',
            'ip': '10.1.2.10',
            'mac': '00:1B:44:11:3A:B8',
            'switchId': 'access-sw-1',
            'portNumber': 4,
            'vlan': 'database-servers',
            'status': 'active',
            'os': 'Red Hat Enterprise Linux 8',
            'services': ['postgresql', 'redis'],
            'location': 'Server Room A'
        },
        {
            'id': 'storage-server-1',
            'name': 'Storage Server 1',
            'type': 'storage',
            'ip': '10.1.3.10',
            'mac': '00:1B:44:11:3A:B9',
            'switchId': 'access-sw-1',
            'portNumber': 5,
            'vlan': 'storage-network',
            'status': 'active',
            'os': 'TrueNAS Scale',
            'services': ['nfs', 'iscsi', 'smb'],
            'location': 'Server Room A'
        },
        {
            'id': 'firewall-1',
            'name': 'Edge Firewall',
            'type': 'security',
            'ip': '192.168.1.1',
            'mac': '00:1B:44:11:3A:BA',
            'switchId': 'core-sw-1',
            'portNumber': 3,
            'vlan': 'dmz',
            'status': 'active',
            'os': 'pfSense 2.7',
            'services': ['firewall', 'vpn', 'ids'],
            'location': 'Network DMZ'
        }
    ]
    
    # Update host-connected ports
    for host in connected_hosts:
        for switch in switches:
            if switch['id'] == host['switchId']:
                for port in switch['ports']:
                    if port['portNumber'] == host['portNumber']:
                        port['connectedTo'] = {
                            'type': 'host',
                            'hostId': host['id'],
                            'hostName': host['name'],
                            'ip': host['ip']
                        }
                        port['status'] = 'CONNECTED'
                        port['vlan'] = host['vlan']
                        port['utilization'] = 45  # Sample host utilization
    
    # Update network state
    network_state['topology'] = {
        'switches': switches,
        'connections': network_connections,
        'hosts': connected_hosts,
        'vlans': [
            {'id': 'default', 'name': 'Default VLAN', 'vlan_id': 1},
            {'id': 'web-servers', 'name': 'Web Servers', 'vlan_id': 100},
            {'id': 'database-servers', 'name': 'Database Servers', 'vlan_id': 200},
            {'id': 'storage-network', 'name': 'Storage Network', 'vlan_id': 300},
            {'id': 'dmz', 'name': 'DMZ Network', 'vlan_id': 99}
        ]
    }
    
    update_network_stats()

def update_network_stats():
    """Update network statistics based on current state"""
    global network_state
    
    all_ports = []
    for switch in network_state['topology']['switches']:
        all_ports.extend(switch['ports'])
    
    network_state['totalPorts'] = len(all_ports)
    network_state['activePorts'] = len([p for p in all_ports if p['status'] == 'CONNECTED' and p['sfpStatus'] == 'correct'])
    network_state['faultyPorts'] = len([p for p in all_ports if p['status'] != 'CONNECTED' or p['sfpStatus'] != 'correct'])

def update_affected_connections(switch_id, port_number, new_status='inactive'):
    """Update connection status when a port is affected by issues"""
    global network_state
    
    connections = network_state['topology'].get('connections', [])
    
    for connection in connections:
        # Check if this connection involves the affected port
        if ((connection['sourceSwitch'] == switch_id and connection['sourcePort'] == port_number) or
            (connection['targetSwitch'] == switch_id and connection['targetPort'] == port_number)):
            
            connection['status'] = new_status
            logger.info(f"Updated connection {connection['id']} status to {new_status} due to port {switch_id}:{port_number} issue")
            
            # When connection goes down, also update the other end of the connection
            if new_status == 'inactive':
                # Find the other port in this connection
                if connection['sourceSwitch'] == switch_id and connection['sourcePort'] == port_number:
                    # Affect the target port
                    other_switch_id = connection['targetSwitch']
                    other_port_number = connection['targetPort']
                else:
                    # Affect the source port
                    other_switch_id = connection['sourceSwitch']
                    other_port_number = connection['sourcePort']
                
                # Update the other port's status
                for switch in network_state['topology']['switches']:
                    if switch['id'] == other_switch_id:
                        for port in switch['ports']:
                            if port['portNumber'] == other_port_number:
                                port['status'] = 'CABLE_CUT'  # Both ports should show cable cut
                                port['lastUpdated'] = datetime.now().isoformat()
                                logger.info(f"Also updated remote port {other_switch_id}:{other_port_number} status to CABLE_CUT")
                                break
                        break

def cut_cable_connection_by_id(connection_id):
    """Simulate cutting a cable by connection ID - affects both ends of the connection"""
    global network_state
    
    connections = network_state['topology'].get('connections', [])
    affected_ports = []
    
    # Find and update the specific connection
    for connection in connections:
        if connection['id'] == connection_id:
            connection['status'] = 'inactive'
            
            # Update both ports - cable is physically severed
            source_switch_id = connection['sourceSwitch']
            source_port_number = connection['sourcePort']
            target_switch_id = connection['targetSwitch']
            target_port_number = connection['targetPort']
            
            # Update source port
            for switch in network_state['topology']['switches']:
                if switch['id'] == source_switch_id:
                    for port in switch['ports']:
                        if port['portNumber'] == source_port_number:
                            port['status'] = 'CABLE_CUT'
                            port['lastUpdated'] = datetime.now().isoformat()
                            affected_ports.append({'switch': switch['name'], 'port': port})
                            break
                    break
            
            # Update target port
            for switch in network_state['topology']['switches']:
                if switch['id'] == target_switch_id:
                    for port in switch['ports']:
                        if port['portNumber'] == target_port_number:
                            port['status'] = 'CABLE_CUT'
                            port['lastUpdated'] = datetime.now().isoformat()
                            affected_ports.append({'switch': switch['name'], 'port': port})
                            break
                    break
            
            logger.info(f"Cable cut simulation: Updated connection {connection['id']} and both ports to CABLE_CUT")
            break
    
    return affected_ports

def cut_cable_connection(switch_id, port_number):
    """Legacy function - simulate cutting a cable by finding connection from switch/port"""
    global network_state
    
    connections = network_state['topology'].get('connections', [])
    affected_ports = []
    
    # Find and update the connection and both ports
    for connection in connections:
        if ((connection['sourceSwitch'] == switch_id and connection['sourcePort'] == port_number) or
            (connection['targetSwitch'] == switch_id and connection['targetPort'] == port_number)):
            
            return cut_cable_connection_by_id(connection['id'])
    
    return affected_ports

def update_connection_for_plugout(switch_id, port_number):
    """Update connection status when a cable is unplugged from one end only"""
    global network_state
    
    connections = network_state['topology'].get('connections', [])
    
    for connection in connections:
        if ((connection['sourceSwitch'] == switch_id and connection['sourcePort'] == port_number) or
            (connection['targetSwitch'] == switch_id and connection['targetPort'] == port_number)):
            
            connection['status'] = 'inactive'
            logger.info(f"Cable plugout simulation: Updated connection {connection['id']} to inactive (cable unplugged from one end)")
            return connection
    
    return None

def update_cable_connection(switch_id, port_number, issue_type='CABLE_CUT'):
    """Legacy function - keeping for backward compatibility with traffic drop"""
    if issue_type == 'CABLE_CUT':
        return cut_cable_connection(switch_id, port_number)
    else:
        # For other issues, just update the connection status
        update_connection_for_plugout(switch_id, port_number)
        return []

def add_issue(issue_type, description, affected_port):
    """Add a new issue to the network state"""
    severity_map = {
        'CABLE_PLUGGED_OUT': 'WARNING',
        'CABLE_CUT': 'CRITICAL',
        'TRAFFIC_DROP': 'WARNING',
        'SFP_MISMATCH': 'ERROR'
    }
    
    issue = {
        'id': str(uuid.uuid4()),
        'type': issue_type,
        'description': description,
        'affectedPort': affected_port,
        'timestamp': datetime.now().isoformat(),
        'severity': severity_map.get(issue_type, 'INFO'),
        'resolved': False
    }
    
    network_state['issues'].append(issue)
    return issue

def find_port(switch_id=None, port_number=None):
    """Find a port by switch_id and port_number, or return a random port"""
    import random
    
    logger.debug(f"Finding port - switch_id: {switch_id}, port_number: {port_number}")
    
    if switch_id and port_number:
        logger.debug(f"Looking for specific port: {switch_id}, port {port_number}")
        for switch in network_state['topology']['switches']:
            if switch['id'] == switch_id:
                logger.debug(f"Found switch: {switch['name']}")
                for port in switch['ports']:
                    if port['portNumber'] == port_number:
                        logger.debug(f"Found target port: {port['id']}")
                        return switch, port
        
        logger.warning(f"Specific port not found: {switch_id}, port {port_number}")
        raise ValueError(f"Port not found: switch {switch_id}, port {port_number}")
    
    # Random selection
    logger.debug("Selecting random port")
    if not network_state['topology']['switches']:
        raise ValueError("No switches available in network topology")
    
    random_switch = random.choice(network_state['topology']['switches'])
    if not random_switch['ports']:
        raise ValueError(f"No ports available in switch {random_switch['id']}")
    
    random_port = random.choice(random_switch['ports'])
    logger.debug(f"Selected random port: {random_switch['name']} Port {random_port['portNumber']}")
    return random_switch, random_port

# Topology Management Helper Functions

def parse_topology_file(file):
    """Parse topology from uploaded file (JSON, XML, YAML)"""
    try:
        filename = secure_filename(file.filename)
        file_extension = filename.lower().split('.')[-1]
        
        content = file.read().decode('utf-8')
        
        if file_extension == 'json':
            return json.loads(content)
        elif file_extension in ['xml']:
            return parse_xml_topology(content)
        elif file_extension in ['yaml', 'yml']:
            try:
                import yaml
                return yaml.safe_load(content)
            except ImportError:
                raise ValueError("YAML support not available. Install PyYAML: pip install PyYAML")
        else:
            raise ValueError(f"Unsupported file format: {file_extension}. Supported: json, xml, yaml, yml")
            
    except Exception as e:
        raise ValueError(f"Failed to parse topology file: {str(e)}")

def parse_xml_topology(xml_content):
    """Parse XML topology to Python dict"""
    try:
        root = ET.fromstring(xml_content)
        
        # Basic XML to dict conversion for network topology
        topology = {'switches': []}
        
        for switch_elem in root.findall('.//switch'):
            switch = {
                'id': switch_elem.get('id', f"switch-{len(topology['switches'])}"),
                'name': switch_elem.get('name', f"Switch {len(topology['switches']) + 1}"),
                'location': switch_elem.get('location', ''),
                'model': switch_elem.get('model', 'Generic'),
                'ports': []
            }
            
            for port_elem in switch_elem.findall('.//port'):
                port = {
                    'id': port_elem.get('id', f"{switch['id']}-port-{len(switch['ports'])}"),
                    'switchId': switch['id'],
                    'portNumber': int(port_elem.get('number', len(switch['ports']) + 1)),
                    'status': port_elem.get('status', 'CONNECTED'),
                    'sfpType': port_elem.get('sfpType', 'SR'),
                    'sfpStatus': port_elem.get('sfpStatus', 'correct'),
                    'requiredSfpType': port_elem.get('requiredSfpType', 'SR'),
                    'lastUpdated': datetime.now().isoformat()
                }
                switch['ports'].append(port)
            
            topology['switches'].append(switch)
        
        return topology
        
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML format: {str(e)}")

def validate_topology_data(topology_data):
    """Validate topology data structure including connections and hosts"""
    errors = []
    warnings = []
    
    try:
        # Check if topology_data is a dict
        if not isinstance(topology_data, dict):
            errors.append("Topology data must be a JSON object")
            return {'valid': False, 'errors': errors, 'warnings': warnings, 'summary': {}}
        
        # Check for switches array
        if 'switches' not in topology_data:
            errors.append("Missing 'switches' array in topology")
            return {'valid': False, 'errors': errors, 'warnings': warnings, 'summary': {}}
        
        switches = topology_data['switches']
        if not isinstance(switches, list):
            errors.append("'switches' must be an array")
            return {'valid': False, 'errors': errors, 'warnings': warnings, 'summary': {}}
        
        if len(switches) == 0:
            warnings.append("No switches defined in topology")
        
        total_ports = 0
        switch_ids = set()
        port_ids = set()
        
        # Validate each switch
        for i, switch in enumerate(switches):
            if not isinstance(switch, dict):
                errors.append(f"Switch {i} must be an object")
                continue
            
            # Validate switch properties
            if 'id' not in switch:
                errors.append(f"Switch {i} missing required 'id' field")
            else:
                switch_id = switch['id']
                if switch_id in switch_ids:
                    errors.append(f"Duplicate switch ID: {switch_id}")
                switch_ids.add(switch_id)
            
            if 'name' not in switch:
                warnings.append(f"Switch {switch.get('id', i)} missing 'name' field")
            
            # Validate switch type if present
            if 'type' in switch and switch['type'] not in ['core', 'aggregation', 'access', 'edge']:
                warnings.append(f"Switch {switch.get('id', i)} has unusual type: {switch['type']}")
            
            # Validate ports
            if 'ports' not in switch:
                errors.append(f"Switch {switch.get('id', i)} missing 'ports' array")
                continue
            
            ports = switch['ports']
            if not isinstance(ports, list):
                errors.append(f"Switch {switch.get('id', i)} 'ports' must be an array")
                continue
            
            port_numbers = set()
            for j, port in enumerate(ports):
                if not isinstance(port, dict):
                    errors.append(f"Port {j} in switch {switch.get('id', i)} must be an object")
                    continue
                
                # Validate port properties
                if 'id' not in port:
                    errors.append(f"Port {j} in switch {switch.get('id', i)} missing 'id' field")
                else:
                    port_id = port['id']
                    if port_id in port_ids:
                        errors.append(f"Duplicate port ID: {port_id}")
                    port_ids.add(port_id)
                
                if 'portNumber' not in port:
                    errors.append(f"Port {port.get('id', j)} missing 'portNumber' field")
                else:
                    port_num = port['portNumber']
                    if port_num in port_numbers:
                        errors.append(f"Duplicate port number {port_num} in switch {switch.get('id', i)}")
                    port_numbers.add(port_num)
                
                # Validate SFP types (expanded for data center equipment)
                valid_sfp_types = ['SR', 'LR', 'ZR', 'SFP', 'SFP+', 'SFP28', 'QSFP', 'QSFP+', 'QSFP28', 'RJ45']
                if 'sfpType' in port and port['sfpType'] not in valid_sfp_types:
                    warnings.append(f"Port {port.get('id', j)} has unsupported SFP type: {port['sfpType']}")
                
                if 'status' in port and port['status'] not in ['CONNECTED', 'DISCONNECTED', 'FAULTY', 'PLUGGED_OUT', 'CABLE_CUT', 'TRAFFIC_DROP']:
                    warnings.append(f"Port {port.get('id', j)} has unsupported status: {port['status']}")
                
                # Validate port number type and range
                if 'portNumber' in port:
                    try:
                        port_num = int(port['portNumber'])
                        if port_num < 1 or port_num > 128:  # Extended range for data center switches
                            warnings.append(f"Port {port.get('id', j)} has unusual port number: {port_num}")
                    except (ValueError, TypeError):
                        errors.append(f"Port {port.get('id', j)} has invalid port number type: {port['portNumber']}")
                
                # Validate SFP status
                if 'sfpStatus' in port and port['sfpStatus'] not in ['correct', 'incorrect', 'missing', 'mismatch']:
                    warnings.append(f"Port {port.get('id', j)} has unsupported SFP status: {port['sfpStatus']}")
                
                # Validate switchId consistency
                if 'switchId' in port and port['switchId'] != switch.get('id'):
                    warnings.append(f"Port {port.get('id', j)} switchId mismatch: expected {switch.get('id')}, got {port['switchId']}")
                
                # Validate capacity if present
                if 'capacityGbps' in port:
                    try:
                        capacity = float(port['capacityGbps'])
                        if capacity <= 0 or capacity > 1000:  # 0 to 1Tbps range
                            warnings.append(f"Port {port.get('id', j)} has unusual capacity: {capacity} Gbps")
                    except (ValueError, TypeError):
                        warnings.append(f"Port {port.get('id', j)} has invalid capacity type: {port['capacityGbps']}")
                
                # Validate utilization if present
                if 'utilization' in port:
                    try:
                        util = float(port['utilization'])
                        if util < 0 or util > 100:
                            warnings.append(f"Port {port.get('id', j)} has invalid utilization: {util}%")
                    except (ValueError, TypeError):
                        warnings.append(f"Port {port.get('id', j)} has invalid utilization type: {port['utilization']}")
                
                total_ports += 1
        
        # Validate connections if present
        total_connections = 0
        if 'connections' in topology_data:
            connections = topology_data['connections']
            if isinstance(connections, list):
                for k, conn in enumerate(connections):
                    if not isinstance(conn, dict):
                        errors.append(f"Connection {k} must be an object")
                        continue
                    
                    # Check required connection fields
                    required_fields = ['sourceSwitch', 'sourcePort', 'targetSwitch', 'targetPort']
                    for field in required_fields:
                        if field not in conn:
                            errors.append(f"Connection {k} missing required field: {field}")
                    
                    # Validate that referenced switches exist
                    if 'sourceSwitch' in conn and conn['sourceSwitch'] not in switch_ids:
                        errors.append(f"Connection {k} references unknown source switch: {conn['sourceSwitch']}")
                    
                    if 'targetSwitch' in conn and conn['targetSwitch'] not in switch_ids:
                        errors.append(f"Connection {k} references unknown target switch: {conn['targetSwitch']}")
                    
                    total_connections += 1
        
        # Validate hosts if present
        total_hosts = 0
        if 'hosts' in topology_data:
            hosts = topology_data['hosts']
            if isinstance(hosts, list):
                host_ips = set()
                host_macs = set()
                for l, host in enumerate(hosts):
                    if not isinstance(host, dict):
                        errors.append(f"Host {l} must be an object")
                        continue
                    
                    # Check required host fields
                    if 'switchId' in host and host['switchId'] not in switch_ids:
                        errors.append(f"Host {l} references unknown switch: {host['switchId']}")
                    
                    # Validate IP uniqueness
                    if 'ip' in host:
                        if host['ip'] in host_ips:
                            errors.append(f"Duplicate IP address: {host['ip']}")
                        host_ips.add(host['ip'])
                    
                    # Validate MAC uniqueness
                    if 'mac' in host:
                        if host['mac'] in host_macs:
                            errors.append(f"Duplicate MAC address: {host['mac']}")
                        host_macs.add(host['mac'])
                    
                    total_hosts += 1
        
        # Generate summary
        summary = {
            'total_switches': len(switches),
            'total_ports': total_ports,
            'total_connections': total_connections,
            'total_hosts': total_hosts,
            'unique_switch_ids': len(switch_ids),
            'unique_port_ids': len(port_ids)
        }
        
        is_valid = len(errors) == 0
        
        return {
            'valid': is_valid,
            'errors': errors,
            'warnings': warnings,
            'summary': summary
        }
        
    except Exception as e:
        errors.append(f"Validation error: {str(e)}")
        return {'valid': False, 'errors': errors, 'warnings': warnings, 'summary': {}}

def apply_custom_topology(topology_data):
    """Apply custom topology to network state"""
    global network_state
    
    # Validate first
    validation = validate_topology_data(topology_data)
    if not validation['valid']:
        raise ValueError(f"Invalid topology: {', '.join(validation['errors'])}")
    
    # Backup current state
    backup_state = network_state.copy()
    
    try:
        # Reset issues when loading new topology
        network_state['issues'] = []
        
        # Apply new topology
        network_state['topology'] = topology_data
        network_state['id'] = str(uuid.uuid4())
        network_state['timestamp'] = datetime.now().isoformat()
        
        # Update statistics
        update_network_stats()
        
        logger.info(f"Successfully loaded custom topology with {len(topology_data['switches'])} switches")
        
        return {
            'switches_loaded': len(topology_data['switches']),
            'total_ports': network_state['totalPorts'],
            'warnings': validation['warnings']
        }
        
    except Exception as e:
        # Restore backup on error
        network_state = backup_state
        raise e

def handle_topology_file_upload():
    """Handle file upload for topology"""
    if 'file' not in request.files:
        return jsonify({
            'success': False,
            'message': 'No file uploaded',
            'error': 'Missing file'
        }), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({
            'success': False,
            'message': 'No file selected',
            'error': 'Empty filename'
        }), 400
    
    try:
        # Parse the file
        topology_data = parse_topology_file(file)
        
        # Apply the topology
        result = apply_custom_topology(topology_data)
        
        return jsonify({
            'success': True,
            'message': f'Custom topology loaded successfully from {file.filename}',
            'data': {
                'filename': file.filename,
                'loaded_at': datetime.now().isoformat(),
                'switches_count': result['switches_loaded'],
                'total_ports': result['total_ports'],
                'warnings': result['warnings']
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing uploaded topology file: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Failed to load topology from {file.filename}',
            'error': str(e)
        }), 400

def handle_topology_json_data():
    """Handle JSON topology data from request body"""
    try:
        topology_data = request.get_json()
        
        if not topology_data:
            return jsonify({
                'success': False,
                'message': 'No JSON topology data provided',
                'error': 'Empty request body'
            }), 400
        
        # Apply the topology
        result = apply_custom_topology(topology_data)
        
        return jsonify({
            'success': True,
            'message': 'Custom topology loaded successfully from JSON data',
            'data': {
                'loaded_at': datetime.now().isoformat(),
                'switches_count': result['switches_loaded'],
                'total_ports': result['total_ports'],
                'warnings': result['warnings']
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing JSON topology data: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Failed to load topology from JSON data',
            'error': str(e)
        }), 400

def convert_topology_to_xml(topology):
    """Convert topology dict to XML string"""
    try:
        root = ET.Element('network_topology')
        root.set('exported_at', datetime.now().isoformat())
        
        switches_elem = ET.SubElement(root, 'switches')
        
        for switch in topology.get('switches', []):
            switch_elem = ET.SubElement(switches_elem, 'switch')
            switch_elem.set('id', switch.get('id', ''))
            switch_elem.set('name', switch.get('name', ''))
            switch_elem.set('location', switch.get('location', ''))
            switch_elem.set('model', switch.get('model', ''))
            
            ports_elem = ET.SubElement(switch_elem, 'ports')
            
            for port in switch.get('ports', []):
                port_elem = ET.SubElement(ports_elem, 'port')
                port_elem.set('id', port.get('id', ''))
                port_elem.set('number', str(port.get('portNumber', '')))
                port_elem.set('status', port.get('status', ''))
                port_elem.set('sfpType', port.get('sfpType', ''))
                port_elem.set('sfpStatus', port.get('sfpStatus', ''))
                port_elem.set('requiredSfpType', port.get('requiredSfpType', ''))
        
        return ET.tostring(root, encoding='unicode')
        
    except Exception as e:
        raise ValueError(f"Failed to convert topology to XML: {str(e)}")

# API Routes

@app.route('/api/network/status', methods=['GET'])
def get_network_status():
    """Get the current network status overview"""
    try:
        logger.debug("Received network status request")
        update_network_stats()
        
        overview = {
            'totalSwitches': len(network_state['topology']['switches']),
            'totalPorts': network_state['totalPorts'],
            'activePorts': network_state['activePorts'],
            'faultyPorts': network_state['faultyPorts'],
            'totalIssues': len([i for i in network_state['issues'] if not i['resolved']])
        }
        
        if network_state['faultyPorts'] == 0:
            health_status = 'HEALTHY'
        elif network_state['faultyPorts'] < 3:
            health_status = 'DEGRADED'
        else:
            health_status = 'CRITICAL'
        
        response_data = {
            'success': True,
            'data': {
                'id': network_state['id'],
                'timestamp': network_state['timestamp'],
                'overview': overview,
                'healthStatus': health_status
            }
        }
        
        logger.debug(f"Network status: {health_status}, faulty ports: {network_state['faultyPorts']}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in get_network_status: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error getting network status',
            'error': str(e)
        }), 500

@app.route('/api/network/topology', methods=['GET'])
def get_network_topology():
    """Get the complete network topology"""
    update_network_stats()
    return jsonify({
        'success': True,
        'data': network_state['topology']
    })

@app.route('/api/network/topology', methods=['POST'])
def load_custom_topology():
    """Load custom network topology from JSON, XML, or YAML"""
    try:
        logger.info("Received custom topology load request")
        
        # Check if it's a file upload or JSON data
        if 'file' in request.files:
            return handle_topology_file_upload()
        elif request.is_json:
            return handle_topology_json_data()
        else:
            return jsonify({
                'success': False,
                'message': 'No topology data provided. Send JSON data or upload a file.',
                'error': 'Missing topology data'
            }), 400
            
    except Exception as e:
        logger.error(f"Error loading custom topology: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Failed to load custom topology',
            'error': str(e)
        }), 500

@app.route('/api/network/topology/upload', methods=['POST'])
def upload_topology_file():
    """Upload topology file (JSON, XML, YAML)"""
    return handle_topology_file_upload()

@app.route('/api/network/topology/validate', methods=['POST'])
def validate_topology():
    """Validate topology configuration without applying it"""
    try:
        if 'file' in request.files:
            topology_data = parse_topology_file(request.files['file'])
        elif request.is_json:
            topology_data = request.get_json()
        else:
            return jsonify({
                'success': False,
                'message': 'No topology data to validate'
            }), 400
            
        validation_result = validate_topology_data(topology_data)
        
        return jsonify({
            'success': True,
            'message': 'Topology validation completed',
            'data': {
                'valid': validation_result['valid'],
                'errors': validation_result['errors'],
                'warnings': validation_result['warnings'],
                'summary': validation_result['summary']
            }
        })
        
    except Exception as e:
        logger.error(f"Error validating topology: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Failed to validate topology',
            'error': str(e)
        }), 500

@app.route('/api/network/topology/export', methods=['GET'])
def export_topology():
    """Export current topology as JSON"""
    try:
        format_type = request.args.get('format', 'json').lower()
        
        if format_type == 'json':
            return jsonify({
                'success': True,
                'data': network_state['topology'],
                'format': 'json',
                'exported_at': datetime.now().isoformat()
            })
        elif format_type == 'xml':
            xml_data = convert_topology_to_xml(network_state['topology'])
            return xml_data, 200, {'Content-Type': 'application/xml'}
        elif format_type == 'yaml':
            yaml_data = yaml.dump(network_state['topology'], default_flow_style=False)
            return yaml_data, 200, {'Content-Type': 'application/x-yaml'}
        else:
            return jsonify({
                'success': False,
                'message': f'Unsupported export format: {format_type}. Supported: json, xml, yaml'
            }), 400
            
    except Exception as e:
        logger.error(f"Error exporting topology: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Failed to export topology',
            'error': str(e)
        }), 500

@app.route('/api/network/issues', methods=['GET'])
def get_network_issues():
    """Get all network issues"""
    resolved = request.args.get('resolved')
    issues = network_state['issues']
    
    if resolved is not None:
        is_resolved = resolved.lower() == 'true'
        issues = [i for i in issues if i['resolved'] == is_resolved]
    
    return jsonify({
        'success': True,
        'data': issues,
        'count': len(issues)
    })

@app.route('/api/network/simulate/cable-plugout', methods=['POST'])
def simulate_cable_plugout():
    """Simulate a cable being unplugged"""
    try:
        logger.info("Received cable-plugout simulation request")
        
        # Handle JSON data safely - allow empty body
        data = {}
        if request.content_type == 'application/json':
            try:
                raw_data = request.get_json(silent=True)
                if raw_data is not None:
                    data = raw_data
                logger.debug(f"Request data: {data}")
            except Exception as json_error:
                logger.error(f"JSON parsing error: {str(json_error)}")
                return jsonify({
                    'success': False,
                    'message': 'Invalid JSON in request body',
                    'error': str(json_error)
                }), 400
        
        switch_id = data.get('switchId')
        port_number = data.get('portNumber')
        
        logger.debug(f"Target switch: {switch_id}, port: {port_number}")
        
        try:
            target_switch, target_port = find_port(switch_id, port_number)
            logger.debug(f"Found target - Switch: {target_switch['name']}, Port: {target_port['portNumber']}")
        except Exception as find_error:
            logger.error(f"Error finding port: {str(find_error)}")
            return jsonify({
                'success': False,
                'message': 'Error finding target port',
                'error': str(find_error)
            }), 500
        
        # For cable plugout, only the specific port is affected (cable unplugged from this end only)
        target_port['status'] = 'PLUGGED_OUT'
        target_port['lastUpdated'] = datetime.now().isoformat()
        
        # Update the connection status to inactive, but don't affect the other port
        affected_connection = update_connection_for_plugout(target_switch['id'], target_port['portNumber'])
        
        description = f'Cable unplugged from Port {target_port["portNumber"]} on {target_switch["name"]} - remote end still connected'
        affected_ports = [{'switch': target_switch['name'], 'port': target_port}]
        
        try:
            issue = add_issue(
                'CABLE_PLUGGED_OUT',
                description,
                target_port['id']
            )
            logger.info(f"Created issue: {issue['id']}")
        except Exception as issue_error:
            logger.error(f"Error creating issue: {str(issue_error)}")
            return jsonify({
                'success': False,
                'message': 'Error creating issue record',
                'error': str(issue_error)
            }), 500
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Cable plug-out simulation executed',
            'data': {
                'affectedSwitch': target_switch['name'],
                'affectedPort': target_port['portNumber'],
                'portId': target_port['id'],
                'connectionStatus': 'inactive - cable unplugged from one end',
                'issue': issue,
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts']
                }
            }
        }
        
        logger.info("Cable-plugout simulation completed successfully")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in cable-plugout simulation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during cable-plugout simulation',
            'error': str(e)
        }), 500

@app.route('/api/network/simulate/cable-cut', methods=['POST'])
def simulate_cable_cut():
    """Simulate a cable being cut"""
    try:
        logger.info("Received cable-cut simulation request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        connection_id = data.get('connectionId')
        
        # Find the connection to cut
        target_connection = None
        
        if connection_id:
            # Find specific connection by ID
            for connection in network_state['topology'].get('connections', []):
                if connection['id'] == connection_id:
                    target_connection = connection
                    break
            
            if not target_connection:
                return jsonify({
                    'success': False,
                    'message': f'Connection with ID {connection_id} not found',
                    'error': 'Invalid connectionId'
                }), 400
        else:
            # No connection ID provided, select a random active connection
            active_connections = [conn for conn in network_state['topology'].get('connections', []) 
                                if conn.get('status', 'active') == 'active']
            
            if not active_connections:
                return jsonify({
                    'success': False,
                    'message': 'No active connections available to cut',
                    'error': 'No active connections found'
                }), 400
            
            import random
            target_connection = random.choice(active_connections)
            logger.info(f"No connectionId provided, randomly selected connection: {target_connection['id']}")
        
        # Cut the cable - affects both endpoints
        target_connection['status'] = 'inactive'
        
        affected_ports = []
        
        # Update both ports involved in the connection
        source_switch_id = target_connection['sourceSwitch']
        source_port_number = target_connection['sourcePort']
        target_switch_id = target_connection['targetSwitch']
        target_port_number = target_connection['targetPort']
        
        # Update source port
        for switch in network_state['topology']['switches']:
            if switch['id'] == source_switch_id:
                for port in switch['ports']:
                    if port['portNumber'] == source_port_number:
                        port['status'] = 'CABLE_CUT'
                        port['lastUpdated'] = datetime.now().isoformat()
                        affected_ports.append({'switch': switch['name'], 'port': port})
                        break
                break
        
        # Update target port
        for switch in network_state['topology']['switches']:
            if switch['id'] == target_switch_id:
                for port in switch['ports']:
                    if port['portNumber'] == target_port_number:
                        port['status'] = 'CABLE_CUT'
                        port['lastUpdated'] = datetime.now().isoformat()
                        affected_ports.append({'switch': switch['name'], 'port': port})
                        break
                break
        
        # Create issue description that mentions the cable connection being cut
        if len(affected_ports) >= 2:
            description = f'Cable cut on connection {connection_id}: {affected_ports[0]["switch"]} Port {affected_ports[0]["port"]["portNumber"]} ↔ {affected_ports[1]["switch"]} Port {affected_ports[1]["port"]["portNumber"]} - physical cable severed'
        else:
            description = f'Cable cut on connection {connection_id} - physical cable severed'
        
        # Create issue using the first affected port (or any, since cable is cut)
        issue = add_issue(
            'CABLE_CUT',
            description,
            affected_ports[0]['port']['id'] if affected_ports else connection_id
        )
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Cable cut simulation executed',
            'data': {
                'cutConnection': {
                    'id': target_connection['id'],
                    'sourceSwitch': source_switch_id,
                    'sourcePort': source_port_number,
                    'targetSwitch': target_switch_id,
                    'targetPort': target_port_number,
                    'cableType': target_connection.get('cableType', 'unknown'),
                    'cableLength': target_connection.get('cableLength', 'unknown')
                },
                'affectedPorts': [{
                    'switch': ap['switch'],
                    'portNumber': ap['port']['portNumber'],
                    'portId': ap['port']['id']
                } for ap in affected_ports],
                'issue': issue,
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts']
                }
            }
        }
        
        logger.info(f"Cable-cut simulation completed successfully for connection {connection_id}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in cable-cut simulation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during cable-cut simulation',
            'error': str(e)
        }), 500

@app.route('/api/network/simulate/traffic-drop', methods=['POST'])
def simulate_traffic_drop():
    """Simulate traffic drop on a port"""
    try:
        logger.info("Received traffic-drop simulation request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        switch_id = data.get('switchId')
        port_number = data.get('portNumber')
        
        target_switch, target_port = find_port(switch_id, port_number)
        
        target_port['status'] = 'TRAFFIC_DROP'
        target_port['lastUpdated'] = datetime.now().isoformat()
        
        # Update affected connections
        update_affected_connections(target_switch['id'], target_port['portNumber'], 'inactive')
        
        issue = add_issue(
            'TRAFFIC_DROP',
            f'Traffic drop detected on Port {target_port["portNumber"]} on {target_switch["name"]}',
            target_port['id']
        )
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Traffic drop simulation executed',
            'data': {
                'affectedSwitch': target_switch['name'],
                'affectedPort': target_port['portNumber'],
                'portId': target_port['id'],
                'issue': issue,
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts']
                }
            }
        }
        
        logger.info("Traffic-drop simulation completed successfully")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in traffic-drop simulation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during traffic-drop simulation',
            'error': str(e)
        }), 500

@app.route('/api/network/simulate/port-congestion', methods=['POST'])
def simulate_port_congestion():
    """Simulate port congestion / high utilization"""
    try:
        logger.info("Received port-congestion simulation request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        switch_id = data.get('switchId')
        port_number = data.get('portNumber')
        utilization = data.get('utilization', 95.0)  # Default 95%
        
        target_switch, target_port = find_port(switch_id, port_number)
        
        # Set high utilization
        target_port['utilization'] = utilization
        target_port['status'] = 'CONGESTED' if utilization > 90 else 'HIGH_UTILIZATION'
        target_port['lastUpdated'] = datetime.now().isoformat()
        
        # Store congestion start time for tracking
        target_port['congestionStartTime'] = datetime.now().isoformat()
        
        issue = add_issue(
            'PORT_CONGESTION',
            f'Port {target_port["portNumber"]} on {target_switch["name"]} at {utilization}% utilization (threshold: 90%)',
            target_port['id']
        )
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Port congestion simulation executed',
            'data': {
                'affectedSwitch': target_switch['name'],
                'affectedPort': target_port['portNumber'],
                'portId': target_port['id'],
                'utilization': utilization,
                'threshold': 90.0,
                'issue': issue,
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts']
                }
            }
        }
        
        logger.info(f"Port-congestion simulation completed: {utilization}% utilization")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in port-congestion simulation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during port-congestion simulation',
            'error': str(e)
        }), 500

@app.route('/api/network/simulate/vlan-mismatch', methods=['POST'])
def simulate_vlan_mismatch():
    """Simulate VLAN misconfiguration"""
    try:
        logger.info("Received VLAN-mismatch simulation request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        switch_id = data.get('switchId')
        port_number = data.get('portNumber')
        current_vlan = data.get('currentVlan', 100)
        expected_vlan = data.get('expectedVlan', 200)
        
        target_switch, target_port = find_port(switch_id, port_number)
        
        # Set VLAN mismatch
        target_port['vlan'] = current_vlan
        target_port['expectedVlan'] = expected_vlan
        target_port['status'] = 'VLAN_MISMATCH'
        target_port['lastUpdated'] = datetime.now().isoformat()
        
        issue = add_issue(
            'VLAN_MISMATCH',
            f'Port {target_port["portNumber"]} on {target_switch["name"]}: configured VLAN {current_vlan} (expected {expected_vlan})',
            target_port['id']
        )
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'VLAN mismatch simulation executed',
            'data': {
                'affectedSwitch': target_switch['name'],
                'affectedPort': target_port['portNumber'],
                'portId': target_port['id'],
                'currentVlan': current_vlan,
                'expectedVlan': expected_vlan,
                'issue': issue,
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts']
                }
            }
        }
        
        logger.info(f"VLAN-mismatch simulation completed: VLAN {current_vlan} vs expected {expected_vlan}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in VLAN-mismatch simulation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during VLAN-mismatch simulation',
            'error': str(e)
        }), 500

@app.route('/api/network/simulate/link-flap', methods=['POST'])
def simulate_link_flap():
    """Simulate link flapping"""
    try:
        logger.info("Received link-flap simulation request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        connection_id = data.get('connectionId')
        flap_count = data.get('flapCount', 10)
        
        # Find the connection
        target_connection = None
        for connection in network_state['topology'].get('connections', []):
            if connection['id'] == connection_id:
                target_connection = connection
                break
        
        if not target_connection:
            # Select random active connection
            active_connections = [conn for conn in network_state['topology'].get('connections', [])
                                if conn.get('status', 'active') == 'active']
            if not active_connections:
                return jsonify({
                    'success': False,
                    'message': 'No active connections available',
                    'error': 'No connections found'
                }), 400
            
            import random
            target_connection = random.choice(active_connections)
            logger.info(f"No connectionId provided, randomly selected: {target_connection['id']}")
        
        # Mark connection as flapping
        target_connection['flapCount'] = flap_count
        target_connection['flapStartTime'] = datetime.now().isoformat()
        target_connection['status'] = 'flapping'
        
        # Mark both ports as link flap
        source_switch_id = target_connection['sourceSwitch']
        source_port_number = target_connection['sourcePort']
        target_switch_id = target_connection['targetSwitch']
        target_port_number = target_connection['targetPort']
        
        affected_ports = []
        
        # Update source port
        for switch in network_state['topology']['switches']:
            if switch['id'] == source_switch_id:
                for port in switch['ports']:
                    if port['portNumber'] == source_port_number:
                        port['status'] = 'LINK_FLAP'
                        port['flapCount'] = flap_count
                        port['lastUpdated'] = datetime.now().isoformat()
                        affected_ports.append({'switch': switch['name'], 'port': port})
                        break
                break
        
        # Update target port
        for switch in network_state['topology']['switches']:
            if switch['id'] == target_switch_id:
                for port in switch['ports']:
                    if port['portNumber'] == target_port_number:
                        port['status'] = 'LINK_FLAP'
                        port['flapCount'] = flap_count
                        port['lastUpdated'] = datetime.now().isoformat()
                        affected_ports.append({'switch': switch['name'], 'port': port})
                        break
                break
        
        issue = add_issue(
            'LINK_FLAP',
            f'Link flapping detected on connection {target_connection["id"]}: {flap_count} state changes in 60 seconds',
            target_connection['id']
        )
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Link flap simulation executed',
            'data': {
                'flapConnection': {
                    'id': target_connection['id'],
                    'sourceSwitch': source_switch_id,
                    'sourcePort': source_port_number,
                    'targetSwitch': target_switch_id,
                    'targetPort': target_port_number
                },
                'flapCount': flap_count,
                'affectedPorts': [{
                    'switch': ap['switch'],
                    'portNumber': ap['port']['portNumber'],
                    'portId': ap['port']['id']
                } for ap in affected_ports],
                'issue': issue,
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts']
                }
            }
        }
        
        logger.info(f"Link-flap simulation completed: {flap_count} flaps on {target_connection['id']}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in link-flap simulation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during link-flap simulation',
            'error': str(e)
        }), 500

@app.route('/api/network/simulate/sfp-mismatch', methods=['POST'])
def simulate_sfp_mismatch():
    """Simulate SFP type mismatch"""
    try:
        logger.info("Received SFP-mismatch simulation request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        switch_id = data.get('switchId')
        port_number = data.get('portNumber')
        wrong_sfp_type = data.get('wrongSfpType')
        
        target_switch, target_port = find_port(switch_id, port_number)
        
        new_sfp_type = wrong_sfp_type or ('LR' if target_port['sfpType'] == 'SR' else 'SR')
        target_port['sfpType'] = new_sfp_type
        target_port['sfpStatus'] = 'incorrect'
        target_port['lastUpdated'] = datetime.now().isoformat()
        
        issue = add_issue(
            'SFP_MISMATCH',
            f'Wrong SFP type ({new_sfp_type}) plugged into Port {target_port["portNumber"]} on {target_switch["name"]}. Required: {target_port["requiredSfpType"]}',
            target_port['id']
        )
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'SFP mismatch simulation executed',
            'data': {
                'affectedSwitch': target_switch['name'],
                'affectedPort': target_port['portNumber'],
                'portId': target_port['id'],
                'wrongSfpType': new_sfp_type,
                'requiredSfpType': target_port['requiredSfpType'],
                'issue': issue,
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts']
                }
            }
        }
        
        logger.info("SFP-mismatch simulation completed successfully")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in SFP-mismatch simulation: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during SFP-mismatch simulation',
            'error': str(e)
        }), 500

@app.route('/api/network/reset', methods=['POST'])
def reset_network():
    """Reset the network to initial healthy state"""
    try:
        logger.info("Received network reset request")
        global network_state
        
        # Reset all ports to healthy state
        for switch in network_state['topology']['switches']:
            for port in switch['ports']:
                port['status'] = 'CONNECTED'
                port['sfpType'] = port['requiredSfpType']
                port['sfpStatus'] = 'correct'
                port['lastUpdated'] = datetime.now().isoformat()
        
        # Reset all connections to active state
        for connection in network_state['topology'].get('connections', []):
            connection['status'] = 'active'
        
        # Clear all issues
        network_state['issues'] = []
        network_state['timestamp'] = datetime.now().isoformat()
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Network reset to healthy state',
            'data': {
                'networkStats': {
                    'activePorts': network_state['activePorts'],
                    'faultyPorts': network_state['faultyPorts'],
                    'totalIssues': len(network_state['issues'])
                }
            }
        }
        
        logger.info("Network reset completed successfully")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in network reset: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during network reset',
            'error': str(e)
        }), 500

@app.route('/api/network/ports/<switch_id>', methods=['GET'])
def get_switch_ports(switch_id):
    """Get all ports for a specific switch"""
    target_switch = None
    for switch in network_state['topology']['switches']:
        if switch['id'] == switch_id:
            target_switch = switch
            break
    
    if not target_switch:
        return jsonify({
            'success': False,
            'message': 'Switch not found',
            'error': f'No switch found with ID: {switch_id}'
        }), 404
    
    return jsonify({
        'success': True,
        'data': {
            'switch': target_switch,
            'ports': target_switch['ports']
        }
    })

@app.route('/api/network/port/<port_id>', methods=['GET'])
def get_port_details(port_id):
    """Get details of a specific port"""
    found_port = None
    parent_switch = None
    
    for switch in network_state['topology']['switches']:
        for port in switch['ports']:
            if port['id'] == port_id:
                found_port = port
                parent_switch = switch
                break
        if found_port:
            break
    
    if not found_port:
        return jsonify({
            'success': False,
            'message': 'Port not found',
            'error': f'No port found with ID: {port_id}'
        }), 404
    
    return jsonify({
        'success': True,
        'data': {
            'port': found_port,
            'switch': {
                'id': parent_switch['id'],
                'name': parent_switch['name'],
                'location': parent_switch['location']
            }
        }
    })

@app.route('/api/network/connections', methods=['GET'])
def get_network_connections():
    """Get all network connections between switches"""
    return jsonify({
        'success': True,
        'data': network_state['topology'].get('connections', []),
        'count': len(network_state['topology'].get('connections', []))
    })

@app.route('/api/network/hosts', methods=['GET'])
def get_network_hosts():
    """Get all connected hosts/servers"""
    return jsonify({
        'success': True,
        'data': network_state['topology'].get('hosts', []),
        'count': len(network_state['topology'].get('hosts', []))
    })

@app.route('/api/network/vlans', methods=['GET'])
def get_network_vlans():
    """Get all configured VLANs"""
    return jsonify({
        'success': True,
        'data': network_state['topology'].get('vlans', []),
        'count': len(network_state['topology'].get('vlans', []))
    })

@app.route('/api/network/switch/<switch_id>/details', methods=['GET'])
def get_switch_details(switch_id):
    """Get detailed information about a specific switch including connected devices"""
    target_switch = None
    for switch in network_state['topology']['switches']:
        if switch['id'] == switch_id:
            target_switch = switch
            break
    
    if not target_switch:
        return jsonify({
            'success': False,
            'message': 'Switch not found',
            'error': f'No switch found with ID: {switch_id}'
        }), 404
    
    # Get connected devices for this switch
    connected_hosts = [host for host in network_state['topology'].get('hosts', []) 
                      if host['switchId'] == switch_id]
    
    # Get switch-to-switch connections
    switch_connections = []
    for conn in network_state['topology'].get('connections', []):
        if conn['sourceSwitch'] == switch_id or conn['targetSwitch'] == switch_id:
            switch_connections.append(conn)
    
    return jsonify({
        'success': True,
        'data': {
            'switch': target_switch,
            'connectedHosts': connected_hosts,
            'switchConnections': switch_connections,
            'totalPorts': len(target_switch['ports']),
            'activePorts': len([p for p in target_switch['ports'] if p['status'] == 'CONNECTED']),
            'hostPorts': len(connected_hosts),
            'switchPorts': len(switch_connections)
        }
    })

@app.route('/api/network/topology/physical', methods=['GET'])
def get_physical_topology():
    """Get physical topology with connections, distances, and cable information"""
    return jsonify({
        'success': True,
        'data': {
            'switches': network_state['topology']['switches'],
            'connections': network_state['topology'].get('connections', []),
            'hosts': network_state['topology'].get('hosts', []),
            'vlans': network_state['topology'].get('vlans', []),
            'summary': {
                'totalSwitches': len(network_state['topology']['switches']),
                'totalConnections': len(network_state['topology'].get('connections', [])),
                'totalHosts': len(network_state['topology'].get('hosts', [])),
                'totalVlans': len(network_state['topology'].get('vlans', []))
            }
        }
    })

@app.route('/api/system/logs', methods=['GET'])
def get_system_logs():
    """Get recent log entries"""
    try:
        lines_count = request.args.get('lines', 100, type=int)
        log_level = request.args.get('level', 'all').upper()
        
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        log_file = os.path.join(logs_dir, 'network_simulation.log')
        
        if not os.path.exists(log_file):
            return jsonify({
                'success': True,
                'message': 'No log file found yet',
                'data': []
            })
        
        # Read last N lines from log file
        log_entries = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                recent_lines = lines[-lines_count:] if len(lines) > lines_count else lines
                
                for line in recent_lines:
                    line = line.strip()
                    if line and (log_level == 'ALL' or log_level in line):
                        log_entries.append(line)
        
        except Exception as e:
            logger.error(f"Error reading log file: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Error reading log file: {str(e)}'
            }), 500
        
        return jsonify({
            'success': True,
            'data': log_entries,
            'count': len(log_entries),
            'log_file': log_file
        })
        
    except Exception as e:
        logger.error(f"Error in get_system_logs: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/system/log-info', methods=['GET'])
def get_log_info():
    """Get logging system information"""
    try:
        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        
        log_files = []
        if os.path.exists(logs_dir):
            for filename in os.listdir(logs_dir):
                if filename.endswith('.log'):
                    filepath = os.path.join(logs_dir, filename)
                    try:
                        stat = os.stat(filepath)
                        log_files.append({
                            'name': filename,
                            'size_bytes': stat.st_size,
                            'size_mb': round(stat.st_size / (1024 * 1024), 2),
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
                    except Exception as e:
                        logger.warning(f"Error reading log file stats for {filename}: {str(e)}")
        
        # Get current log levels
        root_logger = logging.getLogger()
        current_levels = {
            'root': logging.getLevelName(root_logger.level),
            'app': logging.getLevelName(logging.getLogger(__name__).level),
            'werkzeug': logging.getLevelName(logging.getLogger('werkzeug').level)
        }
        
        return jsonify({
            'success': True,
            'data': {
                'logs_directory': logs_dir,
                'log_files': log_files,
                'current_levels': current_levels,
                'handlers_count': len(root_logger.handlers)
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_log_info: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/docs', methods=['GET'])
def get_api_docs():
    """Get API documentation"""
    documentation = {
        'title': "Network Simulation Tool API",
        'version': "1.0.0",
        'description': "AI Agent Tool for simulating network outages and querying network state",
        'baseUrl': f"http://localhost:5000/api",
        'endpoints': {
            "GET /network/status": {
                "description": "Get network overview and statistics",
                "returns": "Network health status, port counts, and issue summary"
            },
            "GET /network/topology": {
                "description": "Get complete network topology",
                "returns": "All switches with their ports and current states"
            },
            "GET /network/issues": {
                "description": "Get all network issues",
                "parameters": {"resolved": "boolean (optional) - filter by resolved status"},
                "returns": "List of all network issues with details"
            },
            "POST /network/simulate/cable-plugout": {
                "description": "Simulate cable being unplugged from one specific port (other end remains connected)",
                "body": {"switchId": "string (optional)", "portNumber": "number (optional)"},
                "returns": "Simulation result with single affected port - connection inactive but remote end still connected"
            },
            "POST /network/simulate/cable-cut": {
                "description": "Simulate cable being physically cut/severed (affects entire link between switches)",
                "body": {"connectionId": "string (optional) - ID of the connection/cable to cut. If not provided, random active connection is selected"},
                "returns": "Simulation result with both affected ports - entire physical cable damaged, both ends down",
                "note": "Use GET /api/network/connections to see available connection IDs"
            },
            "POST /network/simulate/traffic-drop": {
                "description": "Simulate traffic drop on port",
                "body": {"switchId": "string (optional)", "portNumber": "number (optional)"},
                "returns": "Simulation result with affected port details"
            },
            "POST /network/simulate/sfp-mismatch": {
                "description": "Simulate SFP type mismatch",
                "body": {
                    "switchId": "string (optional)",
                    "portNumber": "number (optional)",
                    "wrongSfpType": "string (optional) - SR, LR, or ZR"
                },
                "returns": "Simulation result with SFP details"
            },
            "POST /network/reset": {
                "description": "Reset network to healthy state",
                "returns": "Reset confirmation with updated statistics"
            },
            "GET /network/ports/:switchId": {
                "description": "Get all ports for a specific switch",
                "parameters": {"switchId": "string - switch identifier"},
                "returns": "Switch details with all its ports"
            },
            "GET /network/port/:portId": {
                "description": "Get specific port details",
                "parameters": {"portId": "string - port identifier"},
                "returns": "Detailed port information with parent switch"
            },
            "GET /network/connections": {
                "description": "Get all network connections between switches",
                "returns": "List of switch-to-switch connections with cable information"
            },
            "GET /network/hosts": {
                "description": "Get all connected hosts and servers",
                "returns": "List of connected devices with detailed information"
            },
            "GET /network/vlans": {
                "description": "Get all configured VLANs",
                "returns": "List of VLANs with IDs and subnet information"
            },
            "GET /network/switch/:switchId/details": {
                "description": "Get detailed switch information with connections",
                "parameters": {"switchId": "string - switch identifier"},
                "returns": "Complete switch details including connected devices"
            },
            "GET /network/topology/physical": {
                "description": "Get complete physical topology with connections and hosts",
                "returns": "Full network topology including switches, connections, hosts, and VLANs"
            },
            "GET /system/logs": {
                "description": "Get recent log entries",
                "parameters": {
                    "lines": "number (optional) - number of recent lines to return (default: 100)",
                    "level": "string (optional) - filter by log level: DEBUG, INFO, WARNING, ERROR, ALL (default: ALL)"
                },
                "returns": "Recent log entries from the application log file"
            },
            "GET /system/log-info": {
                "description": "Get logging system information",
                "returns": "Information about log files, sizes, and current logging configuration"
            }
        },
        'networkTopology': {
            'switches': 3,
            'portsPerSwitch': 8,
            'totalPorts': 24,
            'sfpTypes': ["SR (Short Range)", "LR (Long Range)", "ZR (Extended Range)"],
            'portStatuses': ["CONNECTED", "PLUGGED_OUT", "CABLE_CUT", "TRAFFIC_DROP"],
            'sfpStatuses': ["correct", "incorrect"]
        },
        'usageExample': {
            "Check network health": "GET /api/network/status",
            "Simulate random cable issue": "POST /api/network/simulate/cable-plugout",
            "Simulate cable cut on connection": "POST /api/network/simulate/cable-cut with body: {\"connectionId\": \"conn-1\"}",
            "Get all current issues": "GET /api/network/issues?resolved=false",
            "Reset simulation": "POST /api/network/reset"
        }
    }
    
    return jsonify(documentation)

@app.route('/', methods=['GET'])
def serve_index():
    """Serve the web interface"""
    return send_from_directory('public', 'index.html')

@app.route('/<path:filename>', methods=['GET'])
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('public', filename)

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'success': False,
        'message': 'Endpoint not found',
        'availableEndpoints': '/api/docs'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({
        'success': False,
        'message': 'Something went wrong!',
        'error': str(error)
    }), 500

# =============================================================================
# REMEDIATION / FIX EXECUTION ENDPOINTS
# =============================================================================

@app.route('/api/network/redistribute-traffic', methods=['POST'])
def redistribute_traffic():
    """Redistribute traffic across parallel paths to resolve congestion"""
    try:
        logger.info("Received traffic redistribution request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        congested_link = data.get('congestedLink', {})
        alternate_paths = data.get('alternatePaths', [])
        flow_distribution = data.get('flowDistribution', {})
        
        src_switch_id = congested_link.get('src')
        dst_switch_id = congested_link.get('dst')
        
        if not src_switch_id or not dst_switch_id:
            return jsonify({
                'success': False,
                'message': 'Missing required fields: congestedLink.src and congestedLink.dst',
                'error': 'Invalid request parameters'
            }), 400
        
        # Find the congested connection
        congested_connection = None
        for connection in network_state['topology'].get('connections', []):
            if ((connection['sourceSwitch'] == src_switch_id and connection['targetSwitch'] == dst_switch_id) or
                (connection['sourceSwitch'] == dst_switch_id and connection['targetSwitch'] == src_switch_id)):
                congested_connection = connection
                break
        
        if not congested_connection:
            return jsonify({
                'success': False,
                'message': f'Connection not found between {src_switch_id} and {dst_switch_id}',
                'error': 'Connection not found'
            }), 404
        
        # Reduce utilization on congested link
        primary_percentage = flow_distribution.get('primary', 50)
        
        # Find and update congested port
        for switch in network_state['topology']['switches']:
            if switch['id'] == src_switch_id:
                for port in switch['ports']:
                    if port['portNumber'] == congested_connection['sourcePort']:
                        old_utilization = port.get('utilization', 95.0)
                        new_utilization = old_utilization * (primary_percentage / 100.0)
                        port['utilization'] = new_utilization
                        port['status'] = 'CONNECTED'  # No longer congested
                        port['lastUpdated'] = datetime.now().isoformat()
                        logger.info(f"Reduced utilization on {switch['name']} port {port['portNumber']}: {old_utilization}% → {new_utilization}%")
                        break
                break
        
        # Mark any issues as resolved
        for issue in network_state['issues']:
            if issue['type'] == 'PORT_CONGESTION' and not issue.get('resolved', False):
                # Check if this issue is related to the fixed port
                if (issue.get('affectedPort') and 
                    (src_switch_id in str(issue.get('description', '')) or
                     dst_switch_id in str(issue.get('description', '')))):
                    issue['resolved'] = True
                    issue['resolvedTime'] = datetime.now().isoformat()
                    issue['resolutionMethod'] = 'Traffic redistribution by AI agent'
                    logger.info(f"Marked issue {issue['id']} as resolved")
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Traffic redistributed successfully',
            'data': {
                'congestedLink': {
                    'src': src_switch_id,
                    'dst': dst_switch_id,
                    'connectionId': congested_connection['id']
                },
                'alternatePaths': alternate_paths,
                'flowDistribution': flow_distribution,
                'result': {
                    'oldUtilization': 95.0,
                    'newUtilization': round(95.0 * (primary_percentage / 100.0), 1),
                    'status': 'Traffic load balanced'
                },
                'timestamp': datetime.now().isoformat()
            }
        }
        
        logger.info(f"Traffic redistribution completed for {src_switch_id} → {dst_switch_id}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in traffic redistribution: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during traffic redistribution',
            'error': str(e)
        }), 500

@app.route('/api/network/port/<port_id>/vlan', methods=['POST'])
def reconfigure_port_vlan(port_id):
    """Reconfigure VLAN on a specific port"""
    try:
        logger.info(f"Received VLAN reconfiguration request for port {port_id}")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        target_vlan = data.get('vlan')
        
        if not target_vlan:
            return jsonify({
                'success': False,
                'message': 'Missing required field: vlan',
                'error': 'Invalid request parameters'
            }), 400
        
        # Find the port
        target_port = None
        target_switch = None
        for switch in network_state['topology']['switches']:
            for port in switch['ports']:
                if port['id'] == port_id:
                    target_port = port
                    target_switch = switch
                    break
            if target_port:
                break
        
        if not target_port:
            return jsonify({
                'success': False,
                'message': f'Port {port_id} not found',
                'error': 'Port not found'
            }), 404
        
        # Update VLAN
        old_vlan = target_port.get('vlan', 'unknown')
        target_port['vlan'] = target_vlan
        target_port['status'] = 'CONNECTED'  # No longer mismatch
        target_port['lastUpdated'] = datetime.now().isoformat()
        
        # Remove expectedVlan field
        if 'expectedVlan' in target_port:
            del target_port['expectedVlan']
        
        # Mark issues as resolved
        for issue in network_state['issues']:
            if issue['type'] == 'VLAN_MISMATCH' and not issue.get('resolved', False):
                if issue.get('affectedPort') == port_id:
                    issue['resolved'] = True
                    issue['resolvedTime'] = datetime.now().isoformat()
                    issue['resolutionMethod'] = 'VLAN reconfiguration by AI agent'
                    logger.info(f"Marked issue {issue['id']} as resolved")
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'VLAN reconfigured successfully',
            'data': {
                'portId': port_id,
                'switch': target_switch['name'],
                'portNumber': target_port['portNumber'],
                'oldVlan': old_vlan,
                'newVlan': target_vlan,
                'timestamp': datetime.now().isoformat()
            }
        }
        
        logger.info(f"VLAN reconfigured on port {port_id}: {old_vlan} → {target_vlan}")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in VLAN reconfiguration: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during VLAN reconfiguration',
            'error': str(e)
        }), 500

@app.route('/api/network/stabilize-link', methods=['POST'])
def stabilize_flapping_link():
    """Stabilize flapping link by switching to alternate path"""
    try:
        logger.info("Received link stabilization request")
        
        try:
            data = request.get_json() or {}
            logger.debug(f"Request data: {data}")
        except Exception as json_error:
            logger.error(f"JSON parsing error: {str(json_error)}")
            return jsonify({
                'success': False,
                'message': 'Invalid JSON in request body',
                'error': str(json_error)
            }), 400
        
        connection_id = data.get('connectionId')
        alternate_path = data.get('alternatePath', {})
        
        if not connection_id:
            return jsonify({
                'success': False,
                'message': 'Missing required field: connectionId',
                'error': 'Invalid request parameters'
            }), 400
        
        # Find the flapping connection
        flapping_connection = None
        for connection in network_state['topology'].get('connections', []):
            if connection['id'] == connection_id:
                flapping_connection = connection
                break
        
        if not flapping_connection:
            return jsonify({
                'success': False,
                'message': f'Connection {connection_id} not found',
                'error': 'Connection not found'
            }), 404
        
        # Mark flapping link for maintenance
        flapping_connection['status'] = 'maintenance'
        flapping_connection['maintenanceReason'] = 'Link flapping - switched to alternate path'
        flapping_connection['maintenanceStartTime'] = datetime.now().isoformat()
        
        # Update ports
        for switch in network_state['topology']['switches']:
            if switch['id'] == flapping_connection['sourceSwitch']:
                for port in switch['ports']:
                    if port['portNumber'] == flapping_connection['sourcePort']:
                        port['status'] = 'MAINTENANCE'
                        port['lastUpdated'] = datetime.now().isoformat()
                        if 'flapCount' in port:
                            del port['flapCount']
                        break
                break
        
        for switch in network_state['topology']['switches']:
            if switch['id'] == flapping_connection['targetSwitch']:
                for port in switch['ports']:
                    if port['portNumber'] == flapping_connection['targetPort']:
                        port['status'] = 'MAINTENANCE'
                        port['lastUpdated'] = datetime.now().isoformat()
                        if 'flapCount' in port:
                            del port['flapCount']
                        break
                break
        
        # Mark issues as resolved
        for issue in network_state['issues']:
            if issue['type'] == 'LINK_FLAP' and not issue.get('resolved', False):
                if connection_id in str(issue.get('description', '')):
                    issue['resolved'] = True
                    issue['resolvedTime'] = datetime.now().isoformat()
                    issue['resolutionMethod'] = 'Link stabilization by AI agent - traffic moved to alternate path'
                    logger.info(f"Marked issue {issue['id']} as resolved")
        
        update_network_stats()
        
        response_data = {
            'success': True,
            'message': 'Link stabilized successfully',
            'data': {
                'flappingConnection': {
                    'id': connection_id,
                    'status': 'maintenance'
                },
                'alternatePath': alternate_path,
                'action': 'Traffic moved to stable alternate path',
                'timestamp': datetime.now().isoformat()
            }
        }
        
        logger.info(f"Link stabilized: {connection_id} placed in maintenance, traffic moved to alternate path")
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Unexpected error in link stabilization: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': 'Internal server error during link stabilization',
            'error': str(e)
        }), 500

# Initialize network on startup
initialize_network()

if __name__ == '__main__':
    print("🚀 Network Simulation Tool starting on http://localhost:5000")
    print("📚 API Documentation available at http://localhost:5000/api/docs")
    print("🌐 Web Interface available at http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)
