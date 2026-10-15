"""Apply the same bounded source-support audit to each independent proposal."""
from camera_assistant.services.knowledge_citations import (
    citation_candidates,
    review_knowledge_citations,
)


def prepare_composition_citations(advice, hits, conditions=None):
    if advice is None:
        return None
    return advice.model_copy(update={"proposals": [proposal.model_copy(update={
        "knowledge_citation_review": review_knowledge_citations(proposal, hits, conditions),
    }) for proposal in advice.proposals]})


def finalize_composition_citations(advice, hits, conditions=None):
    if advice is None or advice.status == "demo":
        return advice
    proposals = []
    for proposal in advice.proposals:
        reviewed = proposal.knowledge_citation_review
        supported = {item.citation.model_dump_json() for item in reviewed.accepted
                     if item.citation is not None} if reviewed else set()
        reasons = list(proposal.reasons)
        citations = []
        for citation in citation_candidates(proposal.knowledge_citations):
            if hasattr(citation, "model_dump_json") and citation.model_dump_json() in supported:
                if citation.claim not in reasons:
                    reasons.append(citation.claim)
                citation = citation.model_copy(update={"claim_path": f"reasons.{reasons.index(citation.claim)}"})
            citations.append(citation)
        proposal = proposal.model_copy(update={"reasons": reasons, "knowledge_citations": citations})
        report = review_knowledge_citations(proposal, hits, conditions)
        proposals.append(proposal.model_copy(update={"knowledge_citation_review": report}))
    status = "unavailable" if not proposals else (
        "grounded" if all(proposal.knowledge_citation_review.accepted
                          and not proposal.knowledge_citation_review.rejected for proposal in proposals)
        else "unverified")
    return advice.model_copy(update={"proposals": proposals, "status": status})
