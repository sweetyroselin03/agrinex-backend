"""
AgriNex Local PyTorch ML Vision Engine (V2-B ResNet18 Model - 60 Classes)

Safe, lazy-loading inference engine for AgriNex trained ML disease classification model.
Supports automatic Git LFS model downloading if deploying in environments without pre-extracted LFS assets.
"""

import os
import io
import json
import base64
import logging
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, Any, Union

import torch
import torch.nn as nn
from torchvision import transforms, models
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

logger = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = os.getenv(
    "DISEASE_MODEL_PATH",
    str(BASE_DIR / "ai_model_training" / "agrinex_disease_model_v2b_best.pth")
)
DEFAULT_DB_PATH = str(BASE_DIR / "ai_model_training" / "disease_info.json")

LFS_DOWNLOAD_URL = "https://media.githubusercontent.com/media/sweetyroselin03/agrinex-backend/main/ai_model_training/agrinex_disease_model_v2b_best.pth"


def get_inference_transforms(image_size: int = 224) -> transforms.Compose:
    """Exact validation/test image transformation pipeline matching V2-B model training."""
    return transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])


class PyTorchVisionEngine:
    """Inference engine for AgriNex trained ML disease classification model."""

    def __init__(self, model_path: str = None, db_path: str = None):
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.device = torch.device("cpu")
        self.model = None
        self.class_names = []
        self.num_classes = 0
        self.disease_db = {}
        self.is_loaded = False
        self.load_error = None
        self.is_loading = False
        self.transform = get_inference_transforms(224)

    def _ensure_real_model_file(self):
        """Validates model file existence and resolves Git LFS pointer files automatically."""
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if file exists
        if not self.model_path.exists():
            logger.warning(f"[AgriNex ML] Model file missing at {self.model_path}. Attempting LFS download...")
            self._download_lfs_model()
            return

        file_size = os.path.getsize(self.model_path)
        logger.info(f"[AgriNex ML] Model file size: {file_size} bytes")

        # If file size is less than 10MB, it's an LFS pointer file (~130 bytes)
        if file_size < 10_000_000:
            logger.warning(f"[AgriNex ML Warning] File at {self.model_path} is a Git LFS pointer file ({file_size} bytes). Downloading binary weights...")
            self._download_lfs_model()

    def _download_lfs_model(self):
        """Downloads real PyTorch binary model weights from GitHub LFS storage."""
        try:
            logger.info(f"[AgriNex ML] Downloading ResNet18 weights from {LFS_DOWNLOAD_URL}...")
            req = urllib.request.Request(
                LFS_DOWNLOAD_URL,
                headers={"User-Agent": "Mozilla/5.0 (AgriNex Backend Auto-Downloader)"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                with open(self.model_path, "wb") as f:
                    f.write(data)

            downloaded_size = os.path.getsize(self.model_path)
            logger.info(f"[AgriNex ML] Download complete! Model size: {downloaded_size} bytes")
        except Exception as e:
            logger.error(f"[AgriNex ML Error] Failed to download model weights from GitHub LFS: {e}")
            raise e

    def load_model(self):
        """Safely loads and validates the trained ResNet18 V2-B model in CPU memory."""
        if self.is_loaded:
            return

        if self.is_loading:
            return

        self.is_loading = True
        logger.info("[AgriNex ML] Initializing...")
        logger.info(f"[AgriNex ML] Model path: {self.model_path}")

        try:
            # 1. Ensure real binary model checkpoint exists
            self._ensure_real_model_file()

            logger.info("[AgriNex ML] Loading ResNet18 V2-B...")

            # 2. Load checkpoint into CPU memory
            checkpoint = torch.load(self.model_path, map_location=self.device)
            self.class_names = checkpoint.get("class_names", [])
            self.num_classes = checkpoint.get("num_classes", len(self.class_names))

            # 3. Class count validation
            if not self.class_names or self.num_classes != 60:
                err_msg = f"[AgriNex ML Error] Checkpoint must contain 60 classes. Found: {self.num_classes}"
                logger.error(err_msg)
                self.load_error = err_msg
                self.is_loading = False
                raise ValueError(err_msg)

            # 4. Reconstruct ResNet18 architecture & load state_dict
            self.model = models.resnet18(weights=None)
            in_features = self.model.fc.in_features
            self.model.fc = nn.Linear(in_features, self.num_classes)
            self.model.load_state_dict(checkpoint["model_state_dict"])
            self.model.to(self.device)
            self.model.eval()

            # 5. Disease knowledge database loading
            if self.db_path.exists():
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.disease_db = json.load(f)

            # 6. Run dummy tensor inference test
            dummy_input = torch.randn(1, 3, 224, 224).to(self.device)
            with torch.no_grad():
                _ = self.model(dummy_input)

            self.is_loaded = True
            self.load_error = None
            self.is_loading = False

            # REQUIRED STARTUP LOGS
            logger.info("[AgriNex ML] Model loaded successfully")
            logger.info(f"[AgriNex ML] Classes: {self.num_classes}")
            logger.info(f"[AgriNex ML] Device: {self.device.type}")

        except Exception as e:
            self.is_loaded = False
            self.is_loading = False
            self.load_error = str(e)
            logger.error(f"[AgriNex ML Error] Failed to load PyTorch model: {e}")
            raise e

    def _prepare_image(self, image_input: Union[str, bytes, Image.Image]) -> Image.Image:
        """Decodes image input (base64 string, bytes, file path, PIL Image) to RGB PIL Image."""
        if isinstance(image_input, Image.Image):
            return image_input.convert("RGB")

        if isinstance(image_input, bytes):
            return Image.open(io.BytesIO(image_input)).convert("RGB")

        if isinstance(image_input, str):
            if image_input.startswith("data:image"):
                base64_data = image_input.split(",", 1)[1]
                image_bytes = base64.b64decode(base64_data)
                return Image.open(io.BytesIO(image_bytes)).convert("RGB")

            if len(image_input) > 500 and not os.path.exists(image_input):
                try:
                    image_bytes = base64.b64decode(image_input)
                    return Image.open(io.BytesIO(image_bytes)).convert("RGB")
                except Exception:
                    pass

            if os.path.exists(image_input):
                return Image.open(image_input).convert("RGB")

        raise ValueError("Invalid image input format. Expected base64 string, bytes, or valid file path.")

    def predict(self, image_input: Union[str, bytes, Image.Image]) -> Dict[str, Any]:
        """Runs local PyTorch ResNet18 disease classification and enriches with knowledge database."""
        if not self.is_loaded:
            self.load_model()

        if self.load_error or not self.model:
            raise RuntimeError(f"PyTorch Vision Model unavailable: {self.load_error}")

        image = self._prepare_image(image_input)
        input_tensor = self.transform(image).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(input_tensor)
            probabilities = torch.softmax(logits, dim=1).squeeze(0)

        top_prob, top_idx = torch.max(probabilities, dim=0)
        predicted_class = self.class_names[top_idx.item()]
        confidence_percent = round(top_prob.item() * 100.0, 1)

        # Extract plant name and disease name
        if "___" in predicted_class:
            plant_name, disease_raw = predicted_class.split("___", 1)
            plant_name = plant_name.replace("_", " ")
            disease_name = disease_raw.replace("_", " ")
        else:
            plant_name = "Crop"
            disease_name = predicted_class.replace("_", " ")

        is_healthy = "healthy" in disease_name.lower() or disease_name.strip() == "Healthy"
        if is_healthy:
            disease_name = "Healthy Crop"

        # Knowledge database lookup
        db_entry = self.disease_db.get(predicted_class, {})

        symptoms = db_entry.get("symptoms")
        symptoms_str = " ".join(symptoms) if isinstance(symptoms, list) else (symptoms or ("Foliage exhibits lush green structure with no visible necrotic lesions." if is_healthy else f"Visual symptoms indicate {disease_name}."))

        causes = db_entry.get("cause") or ("Optimal microclimate and healthy soil nutrition." if is_healthy else f"Pathogenic infection associated with {disease_name}.")

        prevention = db_entry.get("prevention")
        prevention_str = " ".join(prevention) if isinstance(prevention, list) else (prevention or "Maintain field sanitation, balanced NPK nutrients, and drip irrigation.")

        management = db_entry.get("management")
        management_str = " ".join(management) if isinstance(management, list) else (management or ("No chemical treatment required." if is_healthy else f"Apply recommended agricultural remedies for {disease_name}."))

        severity = "Healthy" if is_healthy else ("Critical" if confidence_percent > 85 else "Warning")

        return {
            "is_valid_crop": True,
            "disease_name": f"{plant_name} {disease_name}".strip() if plant_name not in disease_name else disease_name,
            "raw_class": predicted_class,
            "crop_type": plant_name,
            "confidence": confidence_percent,
            "confidence_level": confidence_percent,
            "severity_level": severity,
            "health_score": 98 if is_healthy else max(20, int(100 - confidence_percent * 0.7)),
            "symptoms": symptoms_str,
            "causes": causes,
            "prevention": prevention_str,
            "treatment": management_str,
            "organic_treatment": f"Apply neem oil or biological controls for {disease_name}.",
            "pesticide_recommendations": f"Consult local agricultural extension for labeled treatment of {disease_name}.",
            "irrigation_recommendations": "Use drip irrigation at soil level. Keep foliage dry.",
            "fertilizer_recommendations": "Maintain balanced N-P-K soil nutrition.",
            "recovery_steps": "1. Prune affected leaves\n2. Apply organic/chemical control\n3. Monitor field weekly",
            "estimated_recovery_time": "N/A" if is_healthy else "10-14 days",
            "weather_risk": "High humidity accelerates spore spread.",
            "prevention_tips": "• Prune infected foliage\n• Space plants for airflow\n• Rotate crops",
            "yield_impact": "None" if is_healthy else "Moderate yield impact if left untreated.",
            "pro_tips": "Inspect leaf undersides weekly under natural morning light.",
            "detected_object": plant_name,
            "model": "ResNet18 V2-B",
            "provider": "custom_ml"
        }

    def get_model_info(self) -> Dict[str, Any]:
        """Returns runtime configuration metadata for /ai/model-info."""
        return {
            "provider": "custom_ml",
            "model": "ResNet18 V2-B",
            "classes": self.num_classes or 60,
            "status": "loaded" if self.is_loaded else ("error" if self.load_error else "unloaded")
        }


# Singleton instance
vision_engine = PyTorchVisionEngine()
