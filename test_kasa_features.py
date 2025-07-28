import asyncio
from kasa import Discover

async def print_device_features():
    print("Discovering Kasa devices...")
    devices = await Discover.discover()
    if not devices:
        print("No Kasa devices found.")
        return
    for addr, dev in devices.items():
        await dev.update()
        print(f"\nDevice: {dev.alias} ({addr})")
        print(f"  Model: {getattr(dev, 'model', 'N/A')}")
        print(f"  MAC: {getattr(dev, 'mac', 'N/A')}")
        print(f"  Is Strip: {hasattr(dev, 'children') and bool(dev.children)}")
        print(f"  Supported Features:")
        for feat in sorted(getattr(dev, 'features', [])):
            print(f"    - {feat}")
        # Energy/Emeter support
        if hasattr(dev, 'emeter_realtime'):
            print("  Emeter (energy) support: YES (parent)")
            try:
                await dev.update()
                er = dev.emeter_realtime
                print(f"    Power:   {getattr(er, 'power', 'N/A')} W")
                print(f"    Voltage: {getattr(er, 'voltage', 'N/A')} V")
                print(f"    Current: {getattr(er, 'current', 'N/A')} A")
            except Exception as ex:
                print(f"    [Error reading emeter: {ex}]")
        else:
            print("  Emeter (energy) support: NO (parent)")
        # Children (outlets)
        if hasattr(dev, 'children') and dev.children:
            for idx, child in enumerate(dev.children):
                await child.update()
                print(f"    Child {idx}: {child.alias}")
                print(f"      Supported Features:")
                for feat in sorted(getattr(child, 'features', [])):
                    print(f"        - {feat}")
                if hasattr(child, 'emeter_realtime'):
                    print("      Emeter (energy) support: YES (child)")
                    try:
                        er = child.emeter_realtime
                        print(f"        Power:   {getattr(er, 'power', 'N/A')} W")
                        print(f"        Voltage: {getattr(er, 'voltage', 'N/A')} V")
                        print(f"        Current: {getattr(er, 'current', 'N/A')} A")
                    except Exception as ex:
                        print(f"        [Error reading emeter: {ex}]")
                else:
                    print("      Emeter (energy) support: NO (child)")

if __name__ == "__main__":
    asyncio.run(print_device_features())
