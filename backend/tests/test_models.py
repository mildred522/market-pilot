from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Project


def test_models_create_projects_table():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    assert "projects" in inspector.get_table_names()


def test_project_model_can_be_persisted():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        project = Project(name="测试面馆", stage="operating")
        session.add(project)
        session.commit()
        session.refresh(project)

        assert project.id is not None
        assert project.name == "测试面馆"
        assert project.stage == "operating"
