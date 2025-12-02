# Assuming your JSON is stored in a variable called `nodes`
nodes = [
    {'id': 'node/NateKunz-Proxmox-Server01', 'name': 'NateKunz-Proxmox-Server01', 'online': 1, 'local': 1, 'ip': '10.0.0.6'},
    {'id': 'node/NateKunz-Proxmox-Server02', 'name': 'NateKunz-Proxmox-Server02', 'online': 1, 'local': 0, 'ip': '10.0.0.7'},
    {'id': 'node/NateKunz-Proxmox-Server03', 'name': 'NateKunz-Proxmox-Server03', 'online': 1, 'local': 0, 'ip': '10.0.0.8'}
]

# Loop through and assign values to variables
for node in nodes:
    name = node['name']
    online = node['online']
    ip = node['ip']
    node_id = node['id']
    
    # Example usage: print or process each variable
    print(f"Name: {name}, Online: {online}, IP: {ip}, ID: {node_id}")