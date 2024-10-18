"""Extension module for FIFA World Cup game."""

import setuptools


with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

    setuptools.setup(
        name="chatbot_fifa_extension",
        version="0.0.14",
        author="Juris Kaminskis",
        author_email="juris@zoozl.net",
        description="FIFA World Cup chatbot extension",
        long_description=long_description,
        long_description_content_type="text/markdown",
        url="https://github.com/Kolumbs/chatbot-fifa-extension",
        install_requires=[
            "zoozl>=0.1.4",
            "membank>=0.4.1",
        ],
        python_requires=">=3.10",
    )
