import machine
import ujson

RTC_MEMORY_SIZE = 2048


def save_to_rtc_memory(state):
    blob = ujson.dumps(state).encode('utf-8')
    if len(blob) >= RTC_MEMORY_SIZE:
        print(f"[RTC_memory] Data overflow! MaxSize: {RTC_MEMORY_SIZE} bytes")
        return False
    machine.RTC().memory(blob)

def load_from_rtc_memory():
    data = machine.RTC().memory()
    if not data:
        return {}
    try:
        return ujson.loads(data)
    except:
        return {}