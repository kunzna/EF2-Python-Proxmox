import json

def get_non_loopback_ipv4(json_data):
    try:
        data = json.loads(json_data)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON format - {e}")
        return []

    ipv4_addresses = []

    try:
        interfaces = data.get("result", [])
        if not interfaces:
            print("No interfaces found in JSON.")
            return []

        for interface in interfaces:
            ip_list = interface.get("ip-addresses", [])
            if not ip_list:
                continue  # Skip interfaces without IP addresses

            for ip_info in ip_list:
                ip_addr = ip_info.get("ip-address")
                if ip_info.get("ip-address-type") == "ipv4" and ip_addr != "127.0.0.1":
                    ipv4_addresses.append(ip_addr)

        if not ipv4_addresses:
            print("No non-loopback IPv4 addresses found.")
        return ipv4_addresses

    except Exception as e:
        print(f"Unexpected error while processing JSON: {e}")
        return []

# Example usage
json_str = """{
    "result": [
        {
            "name": "lo",
            "ip-addresses": [
                {"ip-address-type": "ipv4", "ip-address": "127.0.0.1"},
                {"ip-address-type": "ipv6", "ip-address": "::1"}
            ]
        },
        {
            "name": "ens18",
            "ip-addresses": [
                {"ip-address": "192.168.0.36", "ip-address-type": "ipv4"},
                {"ip-address-type": "ipv6", "ip-address": "fe80::be24:11ff:feec:7d88"}
            ]
        }
    ]
}"""

result = get_non_loopback_ipv4(json_str)
print("Non-loopback IPv4 addresses:", result)