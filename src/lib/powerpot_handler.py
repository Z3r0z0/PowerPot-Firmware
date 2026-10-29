from machine import PWM, Pin, ADC, Timer, disable_irq, enable_irq

from src.lib.enum.log_type import LOG_Type
from src.lib.enum.operation_mode import OPERATION_Mode
from src.lib.enum.operation_state import OPERATION_State

LED_PIN = 8
ADC_PIN = 0
PWM_FORWARD_PIN = 3
MIN_LVL_SENSOR_PIN = 5
TICK_DURATION = 100


class PowerPotHandler:
    def __init__(self, config, server_handler=None, check_update_ms=0):
        self.config = config
        operation_mode = config.get("mode")

        self.server = server_handler

        self._state = OPERATION_State["Idle"]
        self._started = False

        if operation_mode != OPERATION_Mode["Low_Power"]:
            self._check_ticks = int(config.get("checkCycleInterval", 3_600_000)) // TICK_DURATION  # Default 1h
            self._check_update_ticks = int(
                config.get("ota", {}).get("checkCycleInterval", 43_200_000)) // TICK_DURATION  # Default 12h
        else:
            self._check_ticks = 0
            self._check_update_ticks = check_update_ms // TICK_DURATION

        self._pump_running_ticks = 0
        self.pump_pwm_pin = Pin(PWM_FORWARD_PIN, Pin.OUT, Pin.PULL_DOWN)
        self.pump_pwm_pin.value(0)
        self._pump = PWM(self.pump_pwm_pin)
        self._pump.duty(0)
        self._pump.freq(100)

        self._soil_moisture_adc_max = 50_000
        self._soil_moisture_adc_min = 19_500

        self._soil_moisture_adc_step = (self._soil_moisture_adc_max - self._soil_moisture_adc_min) / 100
        self._soil_moisture_adc_watering_min = self._soil_moisture_adc_max - (
                self._soil_moisture_adc_step * config.get("watering", {}).get("minLevel"))
        self._soil_moisture_sensor = ADC(Pin(ADC_PIN, Pin.IN), atten=ADC.ATTN_11DB)

        self._tank_level_sensor = Pin(MIN_LVL_SENSOR_PIN, Pin.IN, Pin.PULL_DOWN)

        self._check_timer = Timer(0)

    def start(self):
        if self._started:
            if self.server:
                self.server.send_log(LOG_Type["system"], "[PowerPot] SYSTEM ALREADY STARTED!")
            return
        self._check_timer.init(mode=Timer.PERIODIC, period=TICK_DURATION, callback=self.on_tick)
        self._started = True
        if self.server:
            self.server.send_log(LOG_Type["system"], f"[PowerPot] SYSTEM STARTED! Mode: {self.config.get('mode')}")

    def on_tick(self, _):
        if self._check_ticks > 0:
            self._check_ticks -= 1
        if self._pump_running_ticks > 0:
            self._pump_running_ticks -= 1
        if self._check_update_ticks > 0:
            self._check_update_ticks -= 1

        if self._pump_running_ticks <= 0 and self._state == OPERATION_State["PumpRunning"]:
            self._state = OPERATION_State["PumpStopRequested"]
        elif self._check_ticks <= 0 and self._state == OPERATION_State["Idle"]:
            self._state = OPERATION_State["MoistureCheck"]

    def should_check_update(self):
        if not self._started or self._state != OPERATION_State["Idle"] or self._check_update_ticks > 0:
            return False

        self._check_update_ticks = int(
            self.config.get("ota", {}).get("checkCycleInterval", 43_200_000)) // TICK_DURATION
        return True

    def get_tank_level(self):
        return self._tank_level_sensor.value()

    def get_current_operation_state(self):
        return self._state

    def get_ota_time_ms(self):
        return self._check_update_ticks * TICK_DURATION

    def run(self):
        if not self._started:
            print("[PowerPot] Not started!")
            return

        # disable interrupts save state
        ir_state = disable_irq()

        try:
            if self._state == OPERATION_State["MoistureCheck"]:
                value = self._soil_moisture_sensor.read_u16()
                percent_value = max(0, min(100, (self._soil_moisture_adc_max - value) / self._soil_moisture_adc_step))

                if value > self._soil_moisture_adc_watering_min:
                    if self.server:
                        self.server.send_log(LOG_Type["watering"], moisture_level=percent_value)
                    print(f"[PowerPot] Watering; Soil Moisture: {percent_value}%")
                    self._pump.duty(int((1023 / 100) * self.config.get("watering", {}).get("pumpPower", 80)))
                    self._state = OPERATION_State["PumpRunning"]
                    self._pump_running_ticks = int(
                        self.config.get("watering", {}).get("wateringDuration", 10_000)) // TICK_DURATION
                else:
                    if self.server:
                        self.server.send_log(LOG_Type["sensor"], name="SoilMoisture", value=percent_value)
                    print(f"[PowerPot] Checked SoilMoisture: {percent_value}%")
                    self._state = OPERATION_State["Idle"]
                self._check_ticks = int(self.config.get("checkCycleInterval", 3_600_000)) // TICK_DURATION
            elif self._state == OPERATION_State["PumpStopRequested"]:
                self._pump.duty(0)
                self._state = OPERATION_State["Idle"]
                print("[PowerPot] Stopped Pump")
        finally:
            # re-enable interrupts with prior state
            enable_irq(ir_state)
