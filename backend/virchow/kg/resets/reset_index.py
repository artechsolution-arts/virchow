from sqlalchemy.orm import Session

from virchow.db.document import reset_all_document_kg_stages
from virchow.db.models import Connector
from virchow.db.models import KGEntity
from virchow.db.models import KGEntityExtractionStaging
from virchow.db.models import KGEntityType
from virchow.db.models import KGRelationship
from virchow.db.models import KGRelationshipExtractionStaging
from virchow.db.models import KGRelationshipType
from virchow.db.models import KGRelationshipTypeExtractionStaging


def reset_full_kg_index__commit(db_session: Session) -> None:
    """
    Resets the knowledge graph index.
    """

    db_session.query(KGRelationship).delete()
    db_session.query(KGRelationshipType).delete()
    db_session.query(KGEntity).delete()
    db_session.query(KGRelationshipExtractionStaging).delete()
    db_session.query(KGEntityExtractionStaging).delete()
    db_session.query(KGRelationshipTypeExtractionStaging).delete()
    # Update all connectors to disable KG processing
    db_session.query(Connector).update({"kg_processing_enabled": False})

    # Only reset grounded entity types
    db_session.query(KGEntityType).filter(
        KGEntityType.grounded_source_name.isnot(None)
    ).update({"active": False})

    reset_all_document_kg_stages(db_session)

    db_session.commit()
