import unittest
import base64
import io
from PIL import Image, ImageDraw

from app.attachments import (
    AttachmentManager,
    get_attachment_manager,
    AttachmentStatus,
    detect_mime_type_from_bytes,
    inspect_image_dimensions
)
from app.vision import VisionService, VisionAnalysisResult
from app.tools import get_tool_registry, ToolContext
from app.graph.workflow import classify_attachment_query


def create_test_image_bytes(format="JPEG", color="red", size=(100, 100), text="TEST") -> bytes:
    """Creates real in-memory image bytes."""
    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 90, 90], outline="blue", fill="yellow")
    draw.text((20, 40), text, fill="black")
    buffer = io.BytesIO()
    img.save(buffer, format=format)
    return buffer.getvalue()


class TestAttachmentVisionPipeline(unittest.TestCase):

    def setUp(self):
        self.manager = get_attachment_manager()
        self.manager.clear()
        self.vision = VisionService()
        self.registry = get_tool_registry()

    def test_valid_jpeg_attachment(self):
        jpeg_bytes = create_test_image_bytes(format="JPEG", color="green", size=(120, 80))
        b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

        att = self.manager.ingest_attachment({
            "name": "photo.jpg",
            "data_url": data_url
        })

        self.assertTrue(att.is_image)
        self.assertEqual(att.mime_type, "image/jpeg")
        self.assertEqual(att.status, AttachmentStatus.READY)
        self.assertEqual(att.dimensions, (120, 80))
        self.assertEqual(att.size, len(jpeg_bytes))
        self.assertIsNotNone(att.get_base64_data_url())

    def test_valid_png_attachment(self):
        png_bytes = create_test_image_bytes(format="PNG", color="blue", size=(200, 150))
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{b64}"

        att = self.manager.ingest_attachment({
            "name": "diagram.png",
            "data_url": data_url
        })

        self.assertTrue(att.is_image)
        self.assertEqual(att.mime_type, "image/png")
        self.assertEqual(att.status, AttachmentStatus.READY)
        self.assertEqual(att.dimensions, (200, 150))

    def test_misleading_filename_is_not_used_for_visual_inference(self):
        # Image contains an obvious real scene (a drawing with yellow box and black text),
        # but the filename says "bg,f8f8f8-flat,750x,075,f-pad,750x1000,f8f8f8.jpg"
        misleading_name = "bg,f8f8f8-flat,750x,075,f-pad,750x1000,f8f8f8.jpg"
        real_image_bytes = create_test_image_bytes(format="JPEG", color="white", size=(300, 200), text="REAL SCENE")
        b64 = base64.b64encode(real_image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

        att = self.manager.ingest_attachment({
            "name": misleading_name,
            "data_url": data_url
        })

        self.assertEqual(att.filename, misleading_name)
        self.assertTrue(att.is_image)
        self.assertEqual(att.dimensions, (300, 200))
        self.assertEqual(att.status, AttachmentStatus.READY)

        # Ensure metadata provides the filename, but does not claim the visual content is plain gray
        meta = att.get_metadata()
        self.assertEqual(meta["filename"], misleading_name)
        self.assertNotIn("gray", str(meta))
        self.assertNotIn("f8f8f8", meta.get("description", ""))

    def test_inaccessible_and_zero_byte_image(self):
        # 0-byte attachment
        att = self.manager.ingest_attachment({
            "name": "empty_capture.png",
            "type": "image/png",
            "size": 0,
            "data_url": ""
        })

        self.assertEqual(att.status, AttachmentStatus.EMPTY_FILE)
        self.assertEqual(att.size, 0)
        self.assertFalse(att.is_image)

        # Attempt visual analysis
        res = self.vision.analyze_image(att)
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "EMPTY_FILE")
        self.assertIn("0 bytes", res.message)
        self.assertIn("cannot infer or guess", res.message)

    def test_missing_attachment_reference(self):
        tool = self.registry.get_tool("analyze_image")
        self.assertIsNotNone(tool)

        res = self.registry.execute("analyze_image", {"attachment_id": "non_existent_id_999"})
        self.assertFalse(res.success)
        self.assertEqual(res.error["code"], "ATTACHMENT_NOT_FOUND")
        self.assertIn("Do not look in workspace filesystem files", res.error["message"])

    def test_non_image_file_handling(self):
        att = self.manager.ingest_attachment({
            "name": "requirements.txt",
            "type": "text/plain",
            "content": "fastapi>=0.111.0\nuvicorn>=0.30.1"
        })

        self.assertFalse(att.is_image)
        self.assertEqual(att.mime_type, "text/plain")
        self.assertEqual(att.status, AttachmentStatus.READY)
        self.assertEqual(att.text_content, "fastapi>=0.111.0\nuvicorn>=0.30.1")

        # Visual analysis should reject non-images cleanly
        res = self.vision.analyze_image(att)
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, "NON_IMAGE")

    def test_metadata_vs_visual_intent_classification(self):
        # Metadata queries
        self.assertEqual(classify_attachment_query("What image did I send?"), "METADATA")
        self.assertEqual(classify_attachment_query("What is the filename?"), "METADATA")
        self.assertEqual(classify_attachment_query("What file did I attach?"), "METADATA")
        self.assertEqual(classify_attachment_query("what is the size of the image"), "METADATA")

        # Visual queries
        self.assertEqual(classify_attachment_query("What is happening in this image?"), "VISUAL")
        self.assertEqual(classify_attachment_query("Describe this image in detail"), "VISUAL")
        self.assertEqual(classify_attachment_query("What is this image about?"), "VISUAL")
        self.assertEqual(classify_attachment_query("What do you see in the photo?"), "VISUAL")
        self.assertEqual(classify_attachment_query("Analyze this image"), "VISUAL")

        # Unrelated query
        self.assertEqual(classify_attachment_query("Create a python script to calculate primes"), "OTHER")

    def test_capability_tool_get_attachment_info(self):
        png_bytes = create_test_image_bytes(format="PNG", color="purple", size=(64, 64))
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        att = self.manager.ingest_attachment({
            "id": "att_test_123",
            "name": "icon.png",
            "data_url": f"data:image/png;base64,{b64}"
        })

        tool = self.registry.get_tool("get_attachment_info")
        self.assertIsNotNone(tool)

        res = self.registry.execute("get_attachment_info", {"attachment_id": "att_test_123"})
        self.assertTrue(res.success)
        self.assertEqual(res.data["filename"], "icon.png")
        self.assertEqual(res.data["mime_type"], "image/png")
        self.assertEqual(res.data["dimensions"], [64, 64])
        self.assertEqual(res.data["status"], "READY")

    def test_vision_service_mock_call(self):
        # Verify VisionService dispatches real image payload to litellm
        from unittest.mock import patch, MagicMock

        jpeg_bytes = create_test_image_bytes(format="JPEG", color="white", size=(150, 150), text="A vibrant red sports car")
        b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
        att = self.manager.ingest_attachment({
            "name": "bg,f8f8f8-flat,750x,075,f-pad,750x1000,f8f8f8.jpg",
            "data_url": f"data:image/jpeg;base64,{b64}"
        })

        mock_choice = MagicMock()
        mock_choice.message.content = "The image displays a white canvas with a blue-bordered yellow square and bold black text."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("litellm.completion", return_value=mock_response) as mock_litellm:
            res = self.vision.analyze_image(
                attachment=att,
                prompt="What is happening in this image?",
                model="llama-3.2-11b-vision-preview",
                provider="groq"
            )

            self.assertTrue(res.success)
            self.assertEqual(res.description, "The image displays a white canvas with a blue-bordered yellow square and bold black text.")
            
            # Verify multimodal format was passed
            call_kwargs = mock_litellm.call_args[1]
            messages = call_kwargs["messages"]
            user_content = messages[0]["content"]
            
            # Text prompt + Image URL object
            self.assertEqual(len(user_content), 2)
            self.assertEqual(user_content[0]["type"], "text")
            self.assertEqual(user_content[1]["type"], "image_url")
            self.assertTrue(user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
            
            # Verify filename was NEVER passed to vision model to bias inference
            prompt_text = user_content[0]["text"]
            self.assertNotIn("bg,f8f8f8", prompt_text)

    def test_workflow_metadata_vs_visual_separation(self):
        import asyncio
        from unittest.mock import patch, MagicMock
        from app.graph.workflow import execute_run_task

        jpeg_bytes = create_test_image_bytes(format="JPEG", color="red", size=(100, 100))
        b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
        att = self.manager.ingest_attachment({
            "id": "att_run_test",
            "name": "bg,f8f8f8-flat,750x,075,f-pad,750x1000,f8f8f8.jpg",
            "data_url": f"data:image/jpeg;base64,{b64}"
        }, conversation_id="conv_123")

        runs_db = {"run_test_meta": {"status": "pending", "state": {}}}

        # 1. Ask for metadata: "What is the filename?"
        asyncio.run(
            execute_run_task(
                run_id="run_test_meta",
                objective="What is the filename?",
                runs_db=runs_db,
                conversation_id="conv_123",
                attachments=[att.get_metadata()]
            )
        )
        reply_meta = runs_db["run_test_meta"]["state"].get("final_response", "")
        self.assertIn("bg,f8f8f8-flat,750x,075,f-pad,750x1000,f8f8f8.jpg", reply_meta)
        self.assertIn("image/jpeg", reply_meta)

        # 2. Ask for visual analysis: "What is happening in this image?"
        runs_db["run_test_vis"] = {"status": "pending", "state": {}}
        mock_choice = MagicMock()
        mock_choice.message.content = "Visual analysis: A bright red frame with a yellow inner box."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        with patch("litellm.completion", return_value=mock_response):
            asyncio.run(
                execute_run_task(
                    run_id="run_test_vis",
                    objective="What is happening in this image?",
                    runs_db=runs_db,
                    conversation_id="conv_123",
                    attachments=[att.get_metadata()]
                )
            )
        reply_vis = runs_db["run_test_vis"]["state"].get("final_response", "")
        self.assertEqual(reply_vis, "Visual analysis: A bright red frame with a yellow inner box.")

        # 3. 0-byte attachment inquiry
        att_empty = self.manager.ingest_attachment({
            "id": "att_empty_test",
            "name": "broken_capture.png",
            "type": "image/png",
            "size": 0
        }, conversation_id="conv_empty")
        runs_db["run_test_empty"] = {"status": "pending", "state": {}}
        asyncio.run(
            execute_run_task(
                run_id="run_test_empty",
                objective="What is this image about?",
                runs_db=runs_db,
                conversation_id="conv_empty",
                attachments=[att_empty.get_metadata()]
            )
        )
        reply_empty = runs_db["run_test_empty"]["state"].get("final_response", "")
        self.assertIn("0 bytes", reply_empty)
        self.assertIn("cannot infer or guess", reply_empty)


if __name__ == "__main__":
    unittest.main()

