"""Tests for SmartChain skill system."""

import tempfile
from pathlib import Path

from custom_components.smartchain.skills import Skill, load_skills, skills_to_prompt


def test_load_skills_from_directory():
    """Test loading skills from a directory with YAML files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "smartchain" / "skills"
        skills_dir.mkdir(parents=True)

        (skills_dir / "weather.yaml").write_text(
            "name: Weather Expert\n"
            "description: Knows about weather\n"
            "prompt: You know everything about weather forecasts.\n"
        )
        (skills_dir / "cooking.yaml").write_text("name: Chef\nprompt: You are an expert chef.\n")

        skills = load_skills(tmpdir)

        assert len(skills) == 2
        names = {s.name for s in skills}
        assert "Weather Expert" in names
        assert "Chef" in names


def test_load_skills_empty_directory():
    """Test loading skills when directory is empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "smartchain" / "skills"
        skills_dir.mkdir(parents=True)

        skills = load_skills(tmpdir)
        assert skills == []


def test_load_skills_no_directory():
    """Test loading skills when directory does not exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills = load_skills(tmpdir)
        assert skills == []


def test_load_skills_invalid_yaml():
    """Test that invalid YAML files are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "smartchain" / "skills"
        skills_dir.mkdir(parents=True)

        (skills_dir / "bad.yaml").write_text("just a string, not a dict")
        (skills_dir / "good.yaml").write_text("name: Good Skill\nprompt: I work.\n")

        skills = load_skills(tmpdir)
        assert len(skills) == 1
        assert skills[0].name == "Good Skill"


def test_load_skills_missing_fields():
    """Test that skills without name or prompt are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        skills_dir = Path(tmpdir) / "smartchain" / "skills"
        skills_dir.mkdir(parents=True)

        (skills_dir / "no_name.yaml").write_text("prompt: I have no name.\n")
        (skills_dir / "no_prompt.yaml").write_text("name: No Prompt\n")

        skills = load_skills(tmpdir)
        assert skills == []


def test_skills_to_prompt():
    """Test formatting skills as system prompt text."""
    skills = [
        Skill(name="Weather", description="Knows weather", prompt="You know weather."),
        Skill(name="Chef", description="", prompt="You are a chef."),
    ]

    result = skills_to_prompt(skills)

    assert "### Weather — Knows weather" in result
    assert "You know weather." in result
    assert "### Chef" in result
    assert "You are a chef." in result


def test_skills_to_prompt_empty():
    """Test that empty skills list returns empty string."""
    assert skills_to_prompt([]) == ""
