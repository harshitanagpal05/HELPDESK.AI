"""
Unit tests for AutoCloseService

Tests cover:
- System settings fallback behavior
- Ticket status update handling
- Error logging boundaries
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta, timezone

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.auto_close_service import AutoCloseService


class TestAutoCloseService(unittest.TestCase):
    """Test suite for AutoCloseService."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock environment variables
        self.env_patcher = patch.dict(os.environ, {
            'SUPABASE_URL': 'https://test.supabase.co',
            'SUPABASE_SERVICE_ROLE_KEY': 'test-key',
            'AUTO_CLOSE_ENABLED': 'true',
            'AUTO_CLOSE_DAYS': '7',
            'AUTO_CLOSE_CRON_SCHEDULE': '0 2 * * *'
        })
        self.env_patcher.start()
        
        # Mock Supabase client
        self.mock_supabase_patcher = patch('services.auto_close_service.create_client')
        self.mock_create_client = self.mock_supabase_patcher.start()
        self.mock_supabase = Mock()
        self.mock_create_client.return_value = self.mock_supabase
        
        # Create service instance
        self.service = AutoCloseService()

    def tearDown(self):
        """Clean up test fixtures."""
        self.env_patcher.stop()
        self.mock_supabase_patcher.stop()

    def test_settings_fallback_when_database_error(self):
        """Test that service falls back to defaults when DB query fails."""
        # Arrange: Simulate DB error
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.side_effect = Exception("DB connection failed")
        
        # Act
        settings = self.service.get_system_settings("test-company-id")
        
        # Assert
        self.assertEqual(settings["auto_close_days"], 7)
        self.assertTrue(settings["auto_close_enabled"])

    def test_settings_fallback_when_no_data(self):
        """Test fallback when company has no system_settings record."""
        # Arrange: Return empty data
        mock_response = Mock()
        mock_response.data = None
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_response
        
        # Act
        settings = self.service.get_system_settings("new-company-id")
        
        # Assert
        self.assertEqual(settings["auto_close_days"], 7)
        self.assertTrue(settings["auto_close_enabled"])

    def test_settings_uses_database_values(self):
        """Test that service uses values from database when available."""
        # Arrange
        mock_response = Mock()
        mock_response.data = {
            "auto_close_days": 14,
            "auto_close_enabled": False
        }
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_response
        
        # Act
        settings = self.service.get_system_settings("existing-company-id")
        
        # Assert
        self.assertEqual(settings["auto_close_days"], 14)
        self.assertFalse(settings["auto_close_enabled"])

    def test_close_ticket_success(self):
        """Test successful ticket closure."""
        # Arrange
        mock_response = Mock()
        self.mock_supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = mock_response
        stats = {"closed_count": 0, "error_count": 0}
        
        # Act
        result = self.service._close_ticket("ticket-123", "company-456", stats)
        
        # Assert
        self.assertTrue(result)
        self.assertEqual(stats["closed_count"], 1)
        self.assertEqual(stats["error_count"], 0)

    def test_close_ticket_failure(self):
        """Test ticket closure failure handling."""
        # Arrange: Simulate update failure
        self.mock_supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = Exception("Update failed")
        stats = {"closed_count": 0, "error_count": 0}
        
        # Act
        result = self.service._close_ticket("ticket-123", "company-456", stats)
        
        # Assert
        self.assertFalse(result)
        self.assertEqual(stats["closed_count"], 0)
        self.assertEqual(stats["error_count"], 1)

    def test_run_disabled_service(self):
        """Test that disabled service returns early."""
        # Arrange
        self.service.enabled = False
        
        # Act
        result = self.service.run()
        
        # Assert
        self.assertEqual(result["status"], "disabled")

    def test_run_no_resolved_tickets(self):
        """Test run when no resolved tickets exist."""
        # Arrange
        mock_response = Mock()
        mock_response.data = []
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_response
        
        # Act
        stats = self.service.run()
        
        # Assert
        self.assertEqual(stats["processed_count"], 0)
        self.assertEqual(stats["closed_count"], 0)

    def test_run_skips_disabled_company(self):
        """Test that tickets from disabled companies are skipped."""
        # Arrange: One resolved ticket from company with auto-close disabled
        mock_ticket_response = Mock()
        mock_ticket_response.data = [{
            "id": "ticket-1",
            "company_id": "company-1",
            "status": "resolved",
            "updated_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        }]
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_ticket_response
        
        # Company settings: auto-close disabled
        mock_settings_response = Mock()
        mock_settings_response.data = {
            "auto_close_days": 7,
            "auto_close_enabled": False
        }
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_settings_response
        
        # Act
        stats = self.service.run()
        
        # Assert
        self.assertEqual(stats["skipped_count"], 1)
        self.assertEqual(stats["closed_count"], 0)

    def test_run_closes_old_tickets(self):
        """Test that old resolved tickets are closed."""
        # Arrange: One old resolved ticket
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        mock_ticket_response = Mock()
        mock_ticket_response.data = [{
            "id": "old-ticket",
            "company_id": "company-1",
            "status": "resolved",
            "updated_at": old_date
        }]
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_ticket_response
        
        # Company settings: enabled, 7 days
        mock_settings_response = Mock()
        mock_settings_response.data = {
            "auto_close_days": 7,
            "auto_close_enabled": True
        }
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_settings_response
        
        # Mock successful close
        self.mock_supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = Mock()
        
        # Act
        stats = self.service.run()
        
        # Assert
        self.assertEqual(stats["closed_count"], 1)
        self.assertEqual(stats["processed_count"], 1)

    def test_run_handles_invalid_timestamp(self):
        """Test error handling for invalid timestamp format."""
        # Arrange: Ticket with invalid timestamp
        mock_ticket_response = Mock()
        mock_ticket_response.data = [{
            "id": "bad-ticket",
            "company_id": "company-1",
            "status": "resolved",
            "updated_at": "invalid-timestamp"
        }]
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_ticket_response
        
        # Company settings
        mock_settings_response = Mock()
        mock_settings_response.data = {
            "auto_close_days": 7,
            "auto_close_enabled": True
        }
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_settings_response
        
        # Act
        stats = self.service.run()
        
        # Assert
        self.assertEqual(stats["error_count"], 1)

    def test_run_handles_missing_timestamp(self):
        """Test handling of tickets missing updated_at field."""
        # Arrange: Ticket without updated_at
        mock_ticket_response = Mock()
        mock_ticket_response.data = [{
            "id": "no-date-ticket",
            "company_id": "company-1",
            "status": "resolved"
            # No updated_at field
        }]
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_ticket_response
        
        # Company settings
        mock_settings_response = Mock()
        mock_settings_response.data = {
            "auto_close_days": 7,
            "auto_close_enabled": True
        }
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_settings_response
        
        # Act
        stats = self.service.run()
        
        # Assert: Should be skipped (not counted as error)
        self.assertEqual(stats["processed_count"], 1)

    def test_error_logging_on_company_processing_failure(self):
        """Test error logging when company processing fails."""
        # Arrange: One ticket with old date that would be closed
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        mock_ticket_response = Mock()
        mock_ticket_response.data = [{
            "id": "ticket-1",
            "company_id": "company-1",
            "status": "resolved",
            "updated_at": old_date
        }]
        
        # Create side effect that raises exception for settings query only
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call - tickets query
                return mock_ticket_response
            else:
                # Second call - settings query - raise exception
                raise Exception("Settings fetch failed")
        
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = side_effect
        
        # Act
        stats = self.service.run()
        
        # Assert: errors should be counted for tickets in that company
        self.assertEqual(stats["error_count"], 1)


class TestAutoCloseServiceInitialization(unittest.TestCase):
    """Test service initialization and configuration."""

    @patch.dict(os.environ, {
        'SUPABASE_URL': 'https://test.supabase.co',
        'SUPABASE_SERVICE_ROLE_KEY': 'test-key',
        'AUTO_CLOSE_ENABLED': 'false',
        'AUTO_CLOSE_DAYS': '14',
        'AUTO_CLOSE_CRON_SCHEDULE': '0 0 * * 0'
    })
    @patch('services.auto_close_service.create_client')
    def test_custom_configuration_loaded(self, mock_create_client):
        """Test that custom env vars are loaded correctly."""
        # Arrange
        mock_create_client.return_value = Mock()
        
        # Act
        service = AutoCloseService()
        
        # Assert
        self.assertFalse(service.enabled)
        self.assertEqual(service.default_auto_close_days, 14)
        self.assertEqual(service.cron_schedule, '0 0 * * 0')


class TestAutoCloseServiceSingleton(unittest.TestCase):
    """Test singleton pattern implementation."""

    @patch.dict(os.environ, {
        'SUPABASE_URL': 'https://test.supabase.co',
        'SUPABASE_SERVICE_ROLE_KEY': 'test-key'
    })
    @patch('services.auto_close_service.create_client')
    def test_load_creates_singleton(self, mock_create_client):
        """Test that load() creates singleton instance."""
        # Arrange
        mock_create_client.return_value = Mock()
        
        # Act
        from services.auto_close_service import load, get_instance, _instance
        
        # Reset singleton for test
        import services.auto_close_service as acs
        acs._instance = None
        
        instance1 = load()
        instance2 = get_instance()
        
        # Assert
        self.assertIs(instance1, instance2)


if __name__ == '__main__':
    unittest.main()