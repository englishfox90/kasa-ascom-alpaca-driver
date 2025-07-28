from kasa import Discover
import asyncio

async def test():
    devices = await Discover.discover()
    for addr, dev in devices.items():
        await dev.update()
        print(dev.alias, dev.is_on)
        await dev.turn_on()
        await dev.turn_off()

asyncio.run(test())