"""Extension module for FIFA World Cup game."""

import setuptools


with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

    setuptools.setup(
        name="chatbot_fifa_extension",
        version="0.1.0",
        author="Juris Kaminskis",
        author_email="juris@zoozl.net",
        description="FIFA World Cup chatbot extension",
        long_description=long_description,
        long_description_content_type="text/markdown",
        url="https://github.com/Kolumbs/chatbot-fifa-extension",
        packages=["chatbot_fifa_extension"],
        package_data={"chatbot_fifa_extension": ["data/*.json"]},
        include_package_data=True,
        install_requires=[
            "membank>=0.4.1",
            "pydantic>=2",
        ],
        extras_require={
            "report": ["reportlab>=4", "tzdata"],
        },
        python_requires=">=3.10",
    )
