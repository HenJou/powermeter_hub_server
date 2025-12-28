import pytest
import time
from unittest.mock import MagicMock, patch
from aggregator import Aggregator

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def mock_mqtt():
    return MagicMock()


def test_aggregator_loop_truncation(mock_db, mock_mqtt):
    with patch('aggregator.HISTORY_RETENTION_MONTHS', 1):
        aggregator = Aggregator(mock_db, mock_mqtt, interval_sec=0.1)

        mock_db.get_total_energy.return_value = 12.34

        def side_effect(*args, **kwargs):
            if mock_db.truncate_old_data.call_count >= 1:
                aggregator._stop_event.set()
            return 1

        mock_db.aggregate_hours.side_effect = side_effect

        aggregator.start()
        time.sleep(0.5)
        aggregator.stop()

        assert mock_db.truncate_old_data.called
        assert mock_db.aggregate_hours.called
        assert mock_mqtt.publish_energy.called



def test_aggregator_no_truncation_when_disabled(mock_db, mock_mqtt):
    # Set HISTORY_RETENTION_MONTHS = 0
    with patch('aggregator.HISTORY_RETENTION_MONTHS', 0):
        aggregator = Aggregator(mock_db, mock_mqtt, interval_sec=0.1)
        
        # Stop without joining
        mock_db.aggregate_hours.side_effect = lambda **kwargs: aggregator._stop_event.set() or 1
        
        aggregator.start()
        time.sleep(0.3)
        aggregator.stop()
        
        assert not mock_db.truncate_old_data.called
        assert mock_db.aggregate_hours.called
        assert mock_mqtt.publish_energy.called


def test_aggregator_truncation_interval(mock_db, mock_mqtt):
    # Re-testing logic by calling aggregate_loop once and checking state
    with patch('aggregator.HISTORY_RETENTION_MONTHS', 1):
        aggregator = Aggregator(mock_db, mock_mqtt, interval_sec=0.1)
        
        # Patching wait so it doesn't sleep
        aggregator._stop_event.wait = MagicMock()
        
        # Mocking time to test daily truncation
        # The loop calls time.time() at the beginning of each iteration.
        # Iteration 1: time.time() -> 1000. (now - self._last_truncation_ts) = 1000 - 0 >= 86400 is True if we consider initial last_truncation_ts=0
        # Wait... the code has self._last_truncation_ts = 0.
        # If now = 1000, then 1000 - 0 = 1000. 1000 >= 86400 is FALSE.
        
        # Let's check aggregator.py:
        # if now - self._last_truncation_ts >= 86400:
        
        # So it won't truncate on the very first run if now < 86400.
        
        with patch('time.time', side_effect=[100000, 100000, 100000 + 86400 + 1, 300000]):
            # Iteration 1: now = 100000. 100000 - 0 = 100000 >= 86400. TRUNCATE. _last_truncation_ts = 100000.
            # Iteration 2: now = 100000. 100000 - 100000 = 0 < 86400. NO TRUNCATE.
            # Iteration 3: now = 100000 + 86400 + 1 = 186401. 186401 - 100000 = 86401 >= 86400. TRUNCATE.
            
            # Use a side effect to stop after 3 iterations
            count = 0
            def stop_side_effect(*args, **kwargs):
                nonlocal count
                count += 1
                if count >= 3:
                    aggregator._stop_event.set()
                return 1
            mock_db.aggregate_hours.side_effect = stop_side_effect
            
            aggregator.aggregate_loop()
            
            assert mock_db.truncate_old_data.call_count == 2
            assert aggregator._last_truncation_ts == 186401
