import asyncio
import os
import time
import hashlib
import aiohttp
from nacl.signing import SigningKey

AGGREGATOR_URL = os.getenv("AGGREGATOR_URL", "http://localhost:3000")
VAULT_URL = os.getenv("VAULT_URL", "http://localhost:4000")
DEVICE_ID = "emulator-001"
GEO_STATIC = "50.4501,30.5234"

def generate_keypair():
    signing_key = SigningKey.generate()
    return signing_key, signing_key.verify_key

async def simulate_camera(session, signing_key):
    print("Starting video frame simulation loop (1 frame/10sec for vault)...")
    while True:
        await asyncio.sleep(10) # Увеличим интервал, чтобы не спамить файлами
        
        # 1. Генерация фиктивного файла (видеокадр в формате .mdev)
        # Добавляем крипто-заглушку в заголовок, ломающую стандартные плееры
        magic_header = b"MDEV_SEC_ENCRYPTED_HEADER_"
        fake_video_data = os.urandom(1000) 
        dummy_content = magic_header + fake_video_data
        
        frame_hash = hashlib.sha256(dummy_content).hexdigest()
        filename = f"{frame_hash}.mdev"
        
        # Сохраняем локально временно
        with open(filename, "wb") as f:
            f.write(dummy_content)
            
        # 2. Отправка в Independent Vault
        print(f"Uploading {filename} to Vault...")
        try:
            with open(filename, "rb") as f:
                form = aiohttp.FormData()
                form.add_field('media', f, filename=filename)
                async with session.post(f"{VAULT_URL}/upload", data=form) as vault_resp:
                    if vault_resp.status == 200:
                        print("Vault upload successful.")
        except Exception as e:
            print(f"Vault connection failed: {e}")
            
        # Очистка локального файла
        if os.path.exists(filename):
            os.remove(filename)
        
        # 3. Таймстемп
        timestamp = str(int(time.time()))
        
        # 4. Конкатенация для криптографии: frame_hash + timestamp + geo
        raw_data = f"{frame_hash}{timestamp}{GEO_STATIC}"
        
        # 5. Подпись
        signed = signing_key.sign(raw_data.encode('utf-8'))
        signature_hex = signed.signature.hex()
        
        # 6. Формирование Payload для Агрегатора
        payload = {
            "device_id": DEVICE_ID,
            "pubkey": verify_key.encode().hex(),
            "data": raw_data,
            "signature": signature_hex
        }
        
        print(f"[{timestamp}] Submitting frame hash to Aggregator: {frame_hash[:8]}...")
        try:
            async with session.post(f"{AGGREGATOR_URL}/api/v1/submit-hash", json=payload) as resp:
                if resp.status != 200:
                    print(f"Aggregator error: {resp.status}")
        except Exception as e:
            print(f"Aggregator connection failed: {e}")

async def main():
    print("Initializing Hardware Emulator with Vault Integration...")
    signing_key, verify_key = generate_keypair()
    device_pubkey = verify_key.encode().hex()
    print(f"Device PubKey (Ed25519): {device_pubkey}")

    async with aiohttp.ClientSession() as session:
        await simulate_camera(session, signing_key)

if __name__ == "__main__":
    asyncio.run(main())
