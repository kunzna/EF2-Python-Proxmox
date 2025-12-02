from proxmoxer import ProxmoxAPI


# Connect to Proxmox API

# Connection details
host = '20.119.75.42'
user = 'root@pam'
token_name = 'api'
token_value = 'a1410e20-5b20-43ff-ba4e-864fb5412001'
verify_ssl = False

# Create and initialize Proxmox client
proxmox = ProxmoxAPI(
    host=host,
    user=user,
    token_name=token_name,
    token_value=token_value,
    verify_ssl=verify_ssl
)

# Iterate through all nodes
for node in proxmox.nodes.get():
    node_name = node['node']
#    print(f"Node: {node_name}")

    # --- QEMU VMs ---
    for vm in proxmox.nodes(node_name).qemu.get():
        vmid = vm['vmid']
        vm_name = vm.get('name', 'Unnamed VM')
#        print(f"  [VM] {vm_name} (ID: {vmid})")

        try:
            agent_info = proxmox.nodes(node_name).qemu(vmid).agent.get('network-get-interfaces')
            for interface in agent_info.get('result', []):
                for ip in interface.get('ip-addresses', []):
                    ip_addr = ip.get('ip-address')
                    if ip_addr and ip_addr != '127.0.0.1' and ':' not in ip_addr:  # exclude loopback and IPv6
                        print(ip_addr)
        except Exception as e:
            print(f"    Could not retrieve IP: {e}")

    # --- LXC Containers ---
    for ct in proxmox.nodes(node_name).lxc.get():
        ct_id = ct['vmid']
        ct_name = ct.get('name', 'Unnamed Container')
#        print(f"  [LXC] {ct_name} (ID: {ct_id})")

        try:
            config = proxmox.nodes(node_name).lxc(ct_id).config.get()
            if 'net0' in config:
                net_info = config['net0']
                for part in net_info.split(','):
                    if part.startswith('ip='):
                        ip_addr = part.split('=')[1].split('/')[0]
                        if ip_addr and ip_addr != '127.0.0.1' and ':' not in ip_addr:  # exclude loopback and IPv6
                            print(ip_addr)
            else:
                print("    No IP info found in config")
        except Exception as e:
            print(f"    Could not retrieve IP: {e}")