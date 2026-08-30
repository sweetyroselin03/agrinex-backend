"""
AgriNex Local PyTorch ML Vision Engine (V2-B Model - 60 Classes)

Loads the trained ResNet18 V2-B checkpoint (agrinex_disease_model_v2b_best.pth),
runs CPU inference matching the exact training preprocessing pipeline,
and enriches predictions with the curated disease knowledge database (disease_info.json).
"""

import os
import io
import json
import base64
import logging
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


def get_inference_transforms(image_size: int = 224) -> transforms.Compose:
    """Exact validation/test image transformation pipeline matching V2-B model training."""
    return transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ])


class PyTorchVisionEngine:
    """Singleton inference engine for AgriNex trained ML disease model."""

    def __init__(self, model_path: str = None, db_path: str = None):
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.device = torch.device("cpu")
        self.model = None
        self.class_names = []
        self.num_classes = 0
        self.disease_db = {}
        self.is_loaded = False
        self.transform = get_inference_transforms(224)

    def load_model(self):
        """Loads the trained disease model into CPU memory safely."""
        if self.is_loaded:
            return

        logger.info("[AgriNex ML] Loading trained disease model...")
        logger.info(f"[AgriNex ML] Target model checkpoint path: {self.model_path}")

        if not self.model_path.exists():
            # Try fallback paths
            alt_path = BASE_DIR.parent / "AGRINEX-DISEASE-ML" / "models" / "agrinex_disease_model_v2b_best.pth"
            if alt_path.exists():
                self.model_path = alt_path
            else:
                logger.error(f"[AgriNex ML Error] Model checkpoint not found at {self.model_path}")
                raise FileNotFoundError(f"Model checkpoint not found at {self.model_path}")

        # Load checkpoint
        checkpoint = torch.load(self.model_path, map_location=self.device)
        self.class_names = checkpoint.get("class_names", [])
        self.num_classes = checkpoint.get("num_classes", len(self.class_names))

        if not self.class_names:
            raise ValueError(f"Checkpoint at {self.model_path} missing 'class_names'!")

        # Reconstruct ResNet18 architecture
        self.model = models.resnet18(weights=None)
        in_features = self.model.fc.in_features
        self.model.fc = nn.Linear(in_features, self.num_classes)

        # Load state dictionary
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model.to(self.device)
        self.model.eval()

        # Load disease knowledge database if available
        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.disease_db = json.load(f)
                logger.info(f"[AgriNex ML] Knowledge database loaded from {self.db_path}")
            except Exception as e:
                logger.warning(f"[AgriNex ML Warning] Failed to load disease_info.json: {e}")

        self.is_loaded = True
        logger.info("[AgriNex ML] Disease model loaded successfully")
        logger.info("[AgriNex ML] Scanner ready")

    def _prepare_image(self, image_input: Union[str, bytes, Image.Image]) -> Image.Image:
        """Decodes base64, bytes, or file path to PIL RGB Image."""
        if isinstance(image_input, Image.Image):
            return image_input.convert("RGB")

        if isinstance(image_input, bytes):
            return Image.open(io.BytesIO(image_input)).convert("RGB")

        if isinstance(image_input, str):
            # Handle base64 data URL
            if image_input.startswith("data:image"):
                base64_data = image_input.split(",", 1)[1]
                image_bytes = base64.b64decode(base64_data)
                return Image.open(io.BytesIO(image_bytes)).convert("RGB")
            # Handle standard base64 string
            if len(image_input) > 500 and not os.path.exists(image_input):
                try:
                    image_bytes = base64.b64decode(image_input)
                    return Image.open(io.BytesIO(image_bytes)).convert("RGB")
                except Exception:
                    pass
            # Handle file path
            if os.path.exists(image_input):
                return Image.open(image_input).convert("RGB")

        raise ValueError("Invalid image input format. Expected base64 string, bytes, or valid file path.")

    def predict(self, image_input: Union[str, bytes, Image.Image]) -> Dict[str, Any]:
        """Runs disease classification and enriches with knowledge database information."""
        if not self.is_loaded:
            self.load_model()

        logger.info("[AgriNex ML] Disease inference started")

        image = self._prepare_image(image_input)
        input_tensor = self.transform(image).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self.model(input_tensor)
            probabilities = torch.softmax(logits, dim=1).squeeze(0)

        top_prob, top_idx = torch.max(probabilities, dim=0)
        predicted_class = self.class_names[top_idx.item()]
        confidence_percent = round(top_prob.item() * 100.0, 1)

        logger.info(f"[AgriNex ML] Prediction: {predicted_class}")
        logger.info(f"[AgriNex ML] Confidence: {confidence_percent}%")

        # Extract plant name and disease name from class string (e.g., 'Tomato___Early_blight')
        if "___" in predicted_class:
            plant_name, disease_raw = predicted_class.split("___", 1)
            plant_name = plant_name.replace("_", " ")
            disease_name = disease_raw.replace("_", " ")
        else:
            plant_name = "Crop"
            disease_name = predicted_class.replace("_", " ")

        # Is healthy?
        is_healthy = "healthy" in disease_name.lower() or disease_name.strip() == "Healthy"
        if is_healthy:
            disease_name = "Healthy Crop"

        # Lookup knowledge database entry
        db_entry = self.disease_db.get(predicted_class, {})

        symptoms = db_entry.get("symptoms")
        if isinstance(symptoms, list):
            symptoms_str = " ".join(symptoms)
        else:
            symptoms_str = symptoms or ("No visible symptoms detected. Foliage displays healthy color and structure." if is_healthy else f"Visual indicators consistent with {disease_name}.")

        causes = db_entry.get("cause") or ("Optimal growth conditions and proper maintenance." if is_healthy else f"Infection caused by {disease_name} pathogen under high leaf moisture.")

        prevention = db_entry.get("prevention")
        if isinstance(prevention, list):
            prevention_str = " ".join(prevention)
        else:
            prevention_str = prevention or "Maintain crop field hygiene, proper plant spacing, and regular drip irrigation."

        management = db_entry.get("management")
        if isinstance(management, list):
            management_str = " ".join(management)
        else:
            management_str = management or "No chemical treatment required for healthy foliage." if is_healthy else "Apply recommended agricultural treatment promptly."

        severity = "Healthy" if is_healthy else ("Critical" if confidence_percent > 85 else "Moderate")

        return {
            "is_valid_crop": True,
            "disease_name": f"{plant_name} {disease_name}".strip() if plant_name not in disease_name else disease_name,
            "raw_class": predicted_class,
            "crop_type": plant_name,
            "confidence": confidence_percent,
            "confidence_level": confidence_percent,
            "severity_level": severity,
            "health_score": 98 if is_healthy else None,
            "symptoms": symptoms_str,
            "causes": causes,
            "prevention": prevention_str,
            "treatment": management_str,
            "organic_treatment": f"Apply neem oil or biological controls for {disease_name} prevention.",
            "pesticide_recommendations": f"Consult local agricultural extension for registered fungicides for {disease_name}.",
            "irrigation_recommendations": "Drip irrigation at root level. Keep foliage dry.",
            "fertilizer_recommendations": "Maintain balanced N-P-K soil nutrition.",
            "recovery_steps": "1. Isolate infected foliage.\n2. Apply treatment.\n3. Monitor weekly.",
            "estimated_recovery_time": "N/A" if is_healthy else "10-14 days",
            "weather_risk": "High humidity promotes fungal spore growth.",
            "prevention_tips": f"• Prune infected leaves\n• Ensure wide row spacing\n• Rotate crops annually",
            "yield_impact": "None" if is_healthy else "Moderate yield impact if left untreated.",
            "pro_tips": "Water plants early in the morning so foliage dries quickly under sunlight.",
            "detected_object": plant_name,
            "model": "agrinex_disease_model_v2b_best",
            "provider": "custom_ml"
        }

    def get_model_info(self) -> Dict[str, Any]:
        """Returns engine status and metadata for /ai/model-info."""
        return {
            "provider": "custom_ml",
            "model": "agrinex_disease_model_v2b_best (ResNet18 V2-B 60-Class)",
            "status": "loaded" if self.is_loaded else "ready",
            "num_classes": self.num_classes or 60,
            "device": str(self.device),
            "model_path": str(self.model_path),
            "database_loaded": bool(self.disease_db)
        }


# Singleton engine instance
vision_engine = PyTorchVisionEngine()
