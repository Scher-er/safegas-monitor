import asyncio
from amqtt.broker import Broker

async def run_broker():
    config = {
        'listeners': {
            'default': {
                'type': 'tcp',
                'bind': '0.0.0.0:1883',
            }
        },
        'sys_interval': 10,
        'auth': {
            'allow-anonymous': True
        }
    }
    broker = Broker(config)
    await broker.start()
    print("Broker MQTT local iniciado na porta 1883...")
    
    while True:
        await asyncio.sleep(99999)

if __name__ == '__main__':
    asyncio.run(run_broker())
