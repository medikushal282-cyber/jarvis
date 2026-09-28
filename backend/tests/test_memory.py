import unittest
import os
import shutil
import tempfile
from typing import Dict, Any

from app.memory.hindsight.client import HindsightClient
from app.memory.hindsight.adapter import HindsightAdapter
from app.memory.okf.manager import OKFManager
from app.memory.context_builder import ContextBuilder
from app.memory.extractor import MemoryExtractor
import app.memory.api as memory_api

class TestMemorySubsystem(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test storage
        self.test_dir = tempfile.mkdtemp()
        
        # Override singleton instances in api with test instances
        self.hindsight_client = HindsightClient(storage_dir=os.path.join(self.test_dir, "hindsight"))
        self.hindsight_adapter = HindsightAdapter(client=self.hindsight_client)
        self.okf_manager = OKFManager(storage_dir=os.path.join(self.test_dir, "okf"))
        self.context_builder = ContextBuilder(hindsight=self.hindsight_adapter, okf=self.okf_manager)
        
        # Patch API module singletons
        memory_api._hindsight_adapter = self.hindsight_adapter
        memory_api._okf_manager = self.okf_manager
        memory_api._context_builder = self.context_builder

    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.test_dir)

    def test_record_experience_and_recall(self):
        user_id = "test_user_1"
        objective = "set up a new Python project"
        
        # 1. Record a successful experience
        fake_state_1 = {
            "status": "completed",
            "artifacts": [{"path": "main.py"}, {"path": "requirements.txt"}],
            "tool_calls": [{"tool": "terminal", "status": "completed"}]
        }
        exp_id = memory_api.record_experience(user_id, objective, fake_state_1)
        self.assertIsNotNone(exp_id)

        # 2. Record a failed experience
        fake_state_2 = {
            "status": "failed",
            "error": "Dependency resolution error: pip install failed on 'unknown-pkg'",
            "tool_calls": [{"tool": "terminal", "status": "failed", "reason": "exit code 1"}]
        }
        memory_api.record_experience(user_id, "install unknown package", fake_state_2)

        # 3. Build context for a similar objective (should recall python setup)
        ctx = memory_api.build_context(user_id, "Set up another Python project")
        self.assertTrue(len(ctx["relevant_experiences"]) >= 1)
        
        # Check that the semantic match correctly pulled up the python project setup
        joined_exps = " ".join(ctx["relevant_experiences"])
        self.assertIn("main.py", joined_exps)

    def test_okf_structured_knowledge(self):
        user_id = "test_user_2"
        project_id = "proj_alpha"
        
        # Write user preferences
        memory_api.update_user_knowledge(user_id, "preferences", "I prefer using React over Angular.", {"confidence": "high"})
        
        # Read back user preferences
        pref = memory_api.get_user_knowledge(user_id, "preferences")
        self.assertEqual(pref["metadata"]["confidence"], "high")
        self.assertEqual(pref["content"], "I prefer using React over Angular.")
        
        # Write project knowledge
        memory_api.update_project_knowledge(user_id, project_id, "architecture", "Uses FastAPI and PostgreSQL.")
        proj_arch = memory_api.get_project_knowledge(user_id, project_id, "architecture")
        self.assertIn("FastAPI", proj_arch["content"])

        # Build context, verify OKF is injected
        ctx = memory_api.build_context(user_id, "build a new feature", project_id=project_id)
        self.assertIn("React", ctx["user_preferences"])

    def test_observation_recording(self):
        user_id = "test_user_3"
        obs = "User consistently creates endpoints in the /api/v1/ namespace."
        obs_id = memory_api.record_observation(user_id, obs)
        self.assertIsNotNone(obs_id)

        ctx = memory_api.build_context(user_id, "create a new endpoint")
        self.assertTrue(any("namespace" in o for o in ctx["relevant_observations"]))

if __name__ == "__main__":
    unittest.main()
