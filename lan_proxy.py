"""Expose the loopback web service to selected devices on the local network."""

import argparse
import asyncio
import ipaddress
import socket


def local_address_for(route_via: str) -> str:
    """Find the current LAN address without relying on a DHCP lease being fixed."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((route_via, 9))
        return sock.getsockname()[0]


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    except (ConnectionError, OSError):
        pass


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-via", default="192.168.1.1")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--allow", action="append", required=True, help="one client IPv4 address")
    args = parser.parse_args()

    allowed = {str(ipaddress.IPv4Address(value)) for value in args.allow}
    bind_ip = local_address_for(args.route_via)
    allowed.add(bind_ip)  # Permits a local health check through the LAN address.

    async def handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        peer = client_writer.get_extra_info("peername")
        if not peer or peer[0] not in allowed:
            client_writer.close()
            await client_writer.wait_closed()
            return
        try:
            backend_reader, backend_writer = await asyncio.open_connection("127.0.0.1", args.port)
            try:
                await asyncio.gather(
                    relay(client_reader, backend_writer),
                    relay(backend_reader, client_writer),
                )
            finally:
                backend_writer.close()
                await backend_writer.wait_closed()
        except (ConnectionError, OSError):
            pass
        finally:
            client_writer.close()
            await client_writer.wait_closed()

    server = await asyncio.start_server(handle, bind_ip, args.port)
    print(f"LAN proxy listening on {bind_ip}:{args.port}; allowed clients: {', '.join(sorted(allowed))}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
