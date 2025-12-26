"""
Tests for Deduplication Reviewer Agents.

Run with: uv run pytest tests/test_dedup_agents.py -v

These tests verify the new reviewer_dedup_be and reviewer_dedup_fe agents
are correctly structured and can be loaded by the AgentLoader.
"""

import re
from pathlib import Path

import pytest
import yaml

# Path to agents directory (at project root, not tests/agents)
AGENTS_DIR = Path(__file__).parent.parent.parent / "agents"


@pytest.mark.unit
class TestDedupAgentFiles:
    """Test 1: Agent files exist and have correct structure."""

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_file_exists(self, agent_name: str):
        """Agent file should exist in agents directory."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        assert agent_path.exists(), f"Agent file {agent_name}.md not found"

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_has_valid_frontmatter(self, agent_name: str):
        """Agent file should have valid YAML frontmatter."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        # Match YAML frontmatter between --- delimiters
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)

        assert match is not None, f"No frontmatter found in {agent_name}"

        # Parse YAML
        try:
            metadata = yaml.safe_load(match.group(1))
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML in {agent_name}: {e}")

        assert metadata is not None, "Frontmatter parsed to None"

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_has_required_fields(self, agent_name: str):
        """Agent frontmatter should have required fields."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        metadata = yaml.safe_load(match.group(1))

        # Required fields
        assert "name" in metadata, "Missing 'name' field"
        assert "description" in metadata, "Missing 'description' field"
        assert "tools" in metadata, "Missing 'tools' field"
        assert "model" in metadata, "Missing 'model' field"

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_name_matches_filename(self, agent_name: str):
        """Agent name in frontmatter should match filename pattern."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        metadata = yaml.safe_load(match.group(1))

        # Name should be kebab-case version of filename
        expected_name = agent_name.replace("_", "-")
        assert (
            metadata["name"] == expected_name
        ), f"Name mismatch: {metadata['name']} != {expected_name}"

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_has_valid_model(self, agent_name: str):
        """Agent model should be a valid Claude model."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)
        metadata = yaml.safe_load(match.group(1))

        valid_models = ["opus", "sonnet", "haiku", "claude-opus-4-5-20251101"]
        assert metadata["model"] in valid_models, f"Invalid model: {metadata['model']}"


@pytest.mark.unit
class TestDedupAgentContent:
    """Test 2: Agent content has correct sections."""

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_has_output_format_section(self, agent_name: str):
        """Agent should define output format."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        assert (
            "## Review Output Format" in content or "## Output Format" in content
        ), "Missing output format section"

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_has_severity_levels(self, agent_name: str):
        """Agent should define severity levels."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        assert "## Severity Levels" in content or "CRITICAL" in content, "Missing severity levels"
        assert "HIGH" in content
        assert "MEDIUM" in content
        assert "LOW" in content

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_has_duplication_types(self, agent_name: str):
        """Agent should define duplication types to detect."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        assert "## Duplication Types" in content, "Missing duplication types section"

    @pytest.mark.parametrize("agent_name", ["reviewer_dedup_be", "reviewer_dedup_fe"])
    def test_agent_has_json_output_schema(self, agent_name: str):
        """Agent should have JSON output schema block."""
        agent_path = AGENTS_DIR / f"{agent_name}.md"
        content = agent_path.read_text()

        # Find JSON code blocks
        json_blocks = re.findall(r"```json\s*\n(.*?)\n```", content, re.DOTALL)
        assert len(json_blocks) > 0, "No JSON schema found"

        # First JSON block should contain the output schema
        first_block = json_blocks[0]
        assert "summary" in first_block, "JSON schema missing 'summary' field"
        assert "duplications" in first_block, "JSON schema missing 'duplications' field"


@pytest.mark.unit
class TestDedupAgentConsistency:
    """Test 3: Both dedup agents are consistent with each other."""

    def test_both_agents_have_same_output_structure(self):
        """Both BE and FE agents should have matching output structure."""
        be_path = AGENTS_DIR / "reviewer_dedup_be.md"
        fe_path = AGENTS_DIR / "reviewer_dedup_fe.md"

        be_content = be_path.read_text()
        fe_content = fe_path.read_text()

        # Extract JSON schemas
        be_json = re.findall(r"```json\s*\n(.*?)\n```", be_content, re.DOTALL)[0]
        fe_json = re.findall(r"```json\s*\n(.*?)\n```", fe_content, re.DOTALL)[0]

        # Both should have same top-level keys
        be_keys = set(re.findall(r'"(\w+)":', be_json))
        fe_keys = set(re.findall(r'"(\w+)":', fe_json))

        # Core keys should be present in both
        core_keys = {"summary", "duplications", "id", "severity", "files", "effort"}
        for key in core_keys:
            assert key in be_keys, f"BE missing key: {key}"
            assert key in fe_keys, f"FE missing key: {key}"

    def test_both_agents_use_same_model(self):
        """Both agents should use the same model for consistency."""
        be_path = AGENTS_DIR / "reviewer_dedup_be.md"
        fe_path = AGENTS_DIR / "reviewer_dedup_fe.md"

        for path in [be_path, fe_path]:
            content = path.read_text()
            match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
            metadata = yaml.safe_load(match.group(1))
            assert metadata["model"] == "opus", f"{path.name} not using opus model"

    def test_both_agents_have_same_tools(self):
        """Both agents should have same tools available."""
        be_path = AGENTS_DIR / "reviewer_dedup_be.md"
        fe_path = AGENTS_DIR / "reviewer_dedup_fe.md"

        be_content = be_path.read_text()
        fe_content = fe_path.read_text()

        be_match = re.match(r"^---\s*\n(.*?)\n---", be_content, re.DOTALL)
        fe_match = re.match(r"^---\s*\n(.*?)\n---", fe_content, re.DOTALL)

        be_metadata = yaml.safe_load(be_match.group(1))
        fe_metadata = yaml.safe_load(fe_match.group(1))

        assert be_metadata["tools"] == fe_metadata["tools"], "Tools mismatch between BE and FE"


@pytest.mark.integration
class TestDedupAgentIntegration:
    """Test 4: Agent integration with AgentLoader."""

    def test_agent_loader_can_load_dedup_be(self):
        """AgentLoader should successfully load reviewer_dedup_be."""
        from turbowrap.chat_cli.agent_loader import AgentLoader

        loader = AgentLoader(agents_dir=AGENTS_DIR)
        agent = loader.get_agent("reviewer_dedup_be")

        assert agent is not None, "Failed to load reviewer_dedup_be"
        assert agent.info["name"] == "reviewer-dedup-be"
        assert len(agent.instructions) > 100, "Instructions too short"

    def test_agent_loader_can_load_dedup_fe(self):
        """AgentLoader should successfully load reviewer_dedup_fe."""
        from turbowrap.chat_cli.agent_loader import AgentLoader

        loader = AgentLoader(agents_dir=AGENTS_DIR)
        agent = loader.get_agent("reviewer_dedup_fe")

        assert agent is not None, "Failed to load reviewer_dedup_fe"
        assert agent.info["name"] == "reviewer-dedup-fe"
        assert len(agent.instructions) > 100, "Instructions too short"

    def test_both_agents_appear_in_list(self):
        """Both dedup agents should appear in agent list."""
        from turbowrap.chat_cli.agent_loader import AgentLoader

        loader = AgentLoader(agents_dir=AGENTS_DIR)
        agents = loader.list_agents()
        agent_names = [a["name"] for a in agents]

        assert "reviewer-dedup-be" in agent_names, "reviewer_dedup_be not in list"
        assert "reviewer-dedup-fe" in agent_names, "reviewer_dedup_fe not in list"


@pytest.mark.integration
class TestOrchestratorIntegration:
    """Test 5: Orchestrator correctly references dedup agents."""

    def test_orchestrator_mentions_dedup_be(self):
        """Orchestrator should mention reviewer_dedup_be."""
        orchestrator_path = AGENTS_DIR / "orchestrator.md"
        content = orchestrator_path.read_text()

        assert "reviewer_dedup_be" in content, "Orchestrator missing reviewer_dedup_be"

    def test_orchestrator_mentions_dedup_fe(self):
        """Orchestrator should mention reviewer_dedup_fe."""
        orchestrator_path = AGENTS_DIR / "orchestrator.md"
        content = orchestrator_path.read_text()

        assert "reviewer_dedup_fe" in content, "Orchestrator missing reviewer_dedup_fe"

    def test_orchestrator_schema_includes_dedup(self):
        """Orchestrator reviewer schema should include dedup reviewers."""
        orchestrator_path = AGENTS_DIR / "orchestrator.md"
        content = orchestrator_path.read_text()

        # Find the reviewer schema line (uses | syntax for alternatives)
        schema_match = re.search(r'"reviewer":\s*"[^"]+"\s*\|[^\n]+', content)
        assert schema_match is not None, "Reviewer schema not found"

        schema = schema_match.group(0)
        assert "reviewer_dedup_be" in schema, f"Dedup BE not in schema: {schema}"
        assert "reviewer_dedup_fe" in schema, f"Dedup FE not in schema: {schema}"

    def test_orchestrator_flow_includes_dedup(self):
        """Orchestrator flow diagram should include dedup reviewers."""
        orchestrator_path = AGENTS_DIR / "orchestrator.md"
        content = orchestrator_path.read_text()

        # Check the flow section mentions dedup
        assert (
            "Backend → reviewer_be + reviewer_dedup_be" in content or "reviewer_dedup_be" in content
        ), "Flow missing BE dedup"
        assert (
            "Frontend → reviewer_fe + reviewer_dedup_fe" in content
            or "reviewer_dedup_fe" in content
        ), "Flow missing FE dedup"


@pytest.mark.unit
class TestDedupAgentSpecificContent:
    """Test 6: Agent-specific content checks."""

    def test_be_agent_mentions_python(self):
        """BE agent should mention Python-specific patterns."""
        agent_path = AGENTS_DIR / "reviewer_dedup_be.md"
        content = agent_path.read_text()

        assert "Python" in content or "python" in content, "BE agent should mention Python"
        assert ".py" in content, "BE agent should mention .py files"

    def test_fe_agent_mentions_typescript(self):
        """FE agent should mention TypeScript-specific patterns."""
        agent_path = AGENTS_DIR / "reviewer_dedup_fe.md"
        content = agent_path.read_text()

        assert (
            "TypeScript" in content or "typescript" in content or "React" in content
        ), "FE agent should mention TypeScript/React"
        assert ".tsx" in content or ".ts" in content, "FE agent should mention .ts/.tsx files"

    def test_be_agent_has_backend_patterns(self):
        """BE agent should have backend-specific patterns."""
        agent_path = AGENTS_DIR / "reviewer_dedup_be.md"
        content = agent_path.read_text()

        # Should mention backend patterns
        backend_patterns = ["service", "repository", "query", "SQL", "validation"]
        found = [p for p in backend_patterns if p.lower() in content.lower()]
        assert len(found) >= 3, f"Missing backend patterns, only found: {found}"

    def test_fe_agent_has_frontend_patterns(self):
        """FE agent should have frontend-specific patterns."""
        agent_path = AGENTS_DIR / "reviewer_dedup_fe.md"
        content = agent_path.read_text()

        # Should mention frontend patterns
        frontend_patterns = ["component", "hook", "useState", "useEffect", "style"]
        found = [p for p in frontend_patterns if p.lower() in content.lower()]
        assert len(found) >= 3, f"Missing frontend patterns, only found: {found}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
