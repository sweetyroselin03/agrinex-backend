import pytest
import sys
from pathlib import Path
from PIL import Image

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.pytorch_vision_engine import vision_engine
from app.ai_service import ai_service
from app.main import app
from fastapi.testclient import TestClient


def test_pytorch_vision_engine_model_loading():
    """Verify PyTorch ResNet18 V2-B model loads with 60 classes on CPU."""
    vision_engine.load_model()
    assert vision_engine.is_loaded is True
    assert vision_engine.num_classes == 60
    assert len(vision_engine.class_names) == 60
    assert str(vision_engine.device) == "cpu"


def test_pytorch_vision_engine_inference():
    """Verify local PyTorch model performs inference without external AI APIs."""
    vision_engine.load_model()
    dummy_img = Image.new("RGB", (224, 224), color=(34, 139, 34))
    res = vision_engine.predict(dummy_img)

    assert "disease_name" in res
    assert "confidence" in res
    assert "symptoms" in res
    assert "causes" in res
    assert "prevention" in res
    assert res["model"] == "ResNet18 V2-B"
    assert res["provider"] == "custom_ml"


def test_model_info_endpoint():
    """Verify /ai/model-info accurately reports custom_ml, groq llama, and disabled gemini."""
    client = TestClient(app)
    res = client.get("/ai/model-info")
    assert res.status_code == 200
    data = res.json()

    assert data["disease_scanner"]["provider"] == "custom_ml"
    assert data["disease_scanner"]["model"] == "ResNet18 V2-B"
    assert data["disease_scanner"]["classes"] == 60
    assert data["disease_scanner"]["status"] == "loaded"

    assert data["ai_chat"]["provider"] == "groq"
    assert data["gemini"]["status"] == "disabled"


def test_no_gemini_or_groq_in_scanner():
    """Verify scanner vision engine has zero Gemini or Groq vision dependencies."""
    assert not hasattr(ai_service.vision_engine, "genai")
    assert not hasattr(ai_service.vision_engine, "client")
    assert ai_service.vision_engine.model is not None
