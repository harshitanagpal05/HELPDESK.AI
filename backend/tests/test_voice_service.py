import pytest
import io
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

@pytest.fixture
def sample_audio_content():
    """Create a dummy WAV-like binary content."""
    # A tiny valid wave header + some dummy data
    # "RIFF" (4) + size (4) + "WAVE" (4) + "fmt " (4) + size (4) + format details (16) + "data" (4) + size (4) + data
    return b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

def test_voice_transcribe_endpoint(sample_audio_content, monkeypatch):
    """Test the /api/voice/transcribe endpoint."""
    
    # Mock the transcribe_audio_async function
    async def mock_transcribe(file_bytes):
        return {
            "transcribed_text": "This is a mock transcription.",
            "detected_language": "en",
            "confidence": 0.99
        }
        
    import backend.main
    # Since endpoint does `from backend.services.voice_service import transcribe_audio_async`,
    # mocking it at the module level.
    import backend.services.voice_service
    monkeypatch.setattr(backend.services.voice_service, "transcribe_audio_async", mock_transcribe)
    
    files = {
        'audio': ('test.webm', io.BytesIO(sample_audio_content), 'audio/webm')
    }
    response = client.post("/api/voice/transcribe", files=files)
    
    assert response.status_code == 200
    data = response.json()
    assert "transcribed_text" in data
    assert data["transcribed_text"] == "This is a mock transcription."
    assert data["detected_language"] == "en"
    assert "confidence" in data
