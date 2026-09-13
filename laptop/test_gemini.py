"""Quick test: verify Gemini API keys and key rotation work correctly."""
import asyncio
import os
import sys
import time

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from app import config
from app.key_pool import GeminiKeyPool


async def test_keys():
    print()
    print("=" * 60)
    print("  GEMINI AI KEY ROTATION TEST")
    print("=" * 60)
    print()

    # 1. Check configured keys
    keys = config.GEMINI_API_KEYS
    print(f"Configured Keys: {len(keys)}")
    for i, k in enumerate(keys):
        masked = k[:8] + "..." + k[-4:]
        label = "PRO (primary)" if i == 0 else f"Normal #{i+1}"
        print(f"  Key {i+1} [{label}]: {masked}")
    
    if not keys:
        print("\n[FAIL] No API keys found! Add GEMINI_API_KEY_1 to laptop/.env")
        return
    
    print(f"  Model: {config.GEMINI_MODEL}")

    # 2. Initialize key pool
    pool = GeminiKeyPool(keys, cooldown=config.GEMINI_COOLDOWN)

    # 3. Test each key individually
    import httpx
    
    print()
    print("=" * 60)
    print("  TESTING EACH KEY INDIVIDUALLY")
    print("=" * 60)
    print()
    
    working_keys = 0
    for i, key in enumerate(keys):
        label = "PRO" if i == 0 else f"Normal #{i+1}"
        
        url = config.GEMINI_URL_TEMPLATE.format(model=config.GEMINI_MODEL, key=key)
        payload = {
            "contents": [{"parts": [{"text": "Reply with exactly one word: WORKING"}]}],
            "generationConfig": {"maxOutputTokens": 20},
        }
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload)
            
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                print(f"  Key {i+1} [{label}]: [OK] Response: {text.strip()[:50]}")
                working_keys += 1
            elif resp.status_code == 429:
                print(f"  Key {i+1} [{label}]: [RATE LIMITED] Key works but needs cooldown")
                working_keys += 1
            elif resp.status_code == 400:
                err = resp.json().get("error", {}).get("message", "Unknown")
                print(f"  Key {i+1} [{label}]: [BAD KEY] {err[:100]}")
            else:
                print(f"  Key {i+1} [{label}]: [ERROR] Status {resp.status_code}")
        except Exception as e:
            print(f"  Key {i+1} [{label}]: [FAIL] {e}")

    # 4. Test rotation (only if we have working keys)
    if working_keys > 0:
        print()
        print("=" * 60)
        print("  TESTING KEY ROTATION (6 rapid requests)")
        print("=" * 60)
        print()
        
        for req_num in range(1, 7):
            key = await pool.next_key()
            if key is None:
                print(f"  Request {req_num}: [NO KEY] All on cooldown")
                continue
            
            key_idx = keys.index(key) + 1 if key in keys else "?"
            masked = key[:8] + "..." + key[-4:]
            
            url = config.GEMINI_URL_TEMPLATE.format(model=config.GEMINI_MODEL, key=key)
            payload = {
                "contents": [{"parts": [{"text": f"Reply: req{req_num}_ok"}]}],
                "generationConfig": {"maxOutputTokens": 20},
            }
            
            start = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(url, json=payload)
                elapsed = time.perf_counter() - start
                
                if resp.status_code == 200:
                    pool.report_success(key)
                    print(f"  Req {req_num} -> Key {key_idx} ({masked}) [OK] {elapsed:.1f}s")
                elif resp.status_code == 429:
                    pool.report_rate_limit(key)
                    print(f"  Req {req_num} -> Key {key_idx} ({masked}) [429 RATE LIMITED -> cooldown]")
                else:
                    print(f"  Req {req_num} -> Key {key_idx} ({masked}) [ERROR {resp.status_code}]")
            except Exception as e:
                print(f"  Req {req_num} -> Key {key_idx} [FAIL] {e}")
            
            await asyncio.sleep(0.5)

    # 5. Final status
    print()
    print("=" * 60)
    print("  FINAL STATUS")
    print("=" * 60)
    print()
    
    status = pool.status()
    print(f"  Total requests sent: {status['total_requests']}")
    print(f"  Successful:          {status['total_successes']}")
    print(f"  Rate limited (429):  {status['total_rate_limits']}")
    print(f"  Keys available:      {status['available_keys']}/{status['total_keys']}")
    print()
    
    for k in status["keys"]:
        avail = "AVAILABLE" if k["available"] else f"COOLDOWN {k['cooldown_remaining_s']}s"
        print(f"  {k['label']}: {k['requests']} reqs, {k['successes']} ok, {k['rate_limits']} rate-limits -- {avail}")
    
    print()
    if working_keys == len(keys):
        print(f"  >>> ALL {working_keys} KEYS WORKING! You will NEVER be rate limited! <<<")
    elif working_keys > 0:
        print(f"  >>> {working_keys}/{len(keys)} keys working. Add remaining keys to .env <<<")
    else:
        print(f"  >>> NO KEYS WORKING! Check your API keys in .env <<<")
    print()


if __name__ == "__main__":
    asyncio.run(test_keys())
