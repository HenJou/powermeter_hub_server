import unittest
from payload_parser import parse_sensor_line, parse_sensor_payload


class TestParser(unittest.TestCase):
    def test_h1_payload(self):
        line = 'MAC123|694851F9|v1.0.1|{"data":[[610965,"mA","E1",33314,0,0,65535]]}|39ef0bdc14b52df375b79555f059b52f'
        hub_version = "h1"

        result = parse_sensor_line(line, hub_version)

        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "CT")
        self.assertEqual(result["sid"], "MAC123")
        self.assertEqual(result["label"], "efergy_h1_MAC123")
        self.assertEqual(result["value"], 33314.0)

    def test_h2_single_sensor_payload(self):
        line = "741459|1|EFCT|P1,2479.98"
        hub_version = "h2"
        
        result = parse_sensor_line(line, hub_version)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "CT")
        self.assertEqual(result["sid"], "741459")
        self.assertEqual(result["label"], "efergy_h2_741459")
        self.assertEqual(result["value"], 2479.98)
        self.assertEqual(result["hub_version"], "h2")

    def test_h2_multi_sensor_example(self):
        line = "747952|0|EFMS1|M,96.00&T,0.00&L,0.00|-67"
        hub_version = "h2"
        result = parse_sensor_line(line, hub_version)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "EFMS")
        self.assertEqual(result["sid"], "747952")
        self.assertEqual(result["rssi"], -67.0)
        self.assertIn(("M", 96.00), result["metrics"])

    def test_h3_example(self):
        line = "815751|1|EFCT|P1,391.86|-66"
        hub_version = "h3"
        result = parse_sensor_line(line, hub_version)
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "CT")
        self.assertEqual(result["sid"], "815751")
        self.assertEqual(result["value"], 391.86)
        self.assertEqual(result["rssi"], -66.0)

    def test_efms_payload(self):
        line = "741459|1|EFMS|M,64.00&T,22.50&L,100.00|85"
        hub_version = "h2"
        
        result = parse_sensor_line(line, hub_version)
        
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "EFMS")
        self.assertEqual(result["sid"], "741459")
        self.assertEqual(len(result["metrics"]), 3)
        self.assertIn(("M", 64.00), result["metrics"])
        self.assertIn(("T", 22.50), result["metrics"])
        self.assertIn(("L", 100.00), result["metrics"])
        self.assertEqual(result["rssi"], 85.0)

    def test_hub_status_line(self):
        line = "0|1|STATUS|OK"
        hub_version = "h2"
        result = parse_sensor_line(line, hub_version)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
