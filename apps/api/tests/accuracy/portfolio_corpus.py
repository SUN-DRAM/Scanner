"""docs/next step measures.md Step 3: the 50-domain clean-scan-rate corpus.

Real, live, currently-operating hosts of the kind that would appear on a
prospect's portfolio page — not badssl fixtures, not tech giants, not
typo domains. Sourced 2026-09-14 directly from live directory listings
(Clutch.co's India digital-marketing directory, and a "Top CA firms in
India" roundup), not guessed or invented — every domain below was returned
by a real search/fetch against a real, currently-published page.

Two categories, deliberately not one: Indian digital/web agencies (the
direct audience — they scan their own site and pitch scanning their
clients') and Indian professional-services firms (chartered accountants —
a vertical this product's own outreach already targets, per
docs/Fix scan reliability.md and docs/urgent_scan_corruption.md's test
data). Both are exactly "the hosts that would appear on a prospect's
portfolio page" — small, real, independently-run businesses, not
enterprise-grade infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioHost:
    hostname: str
    category: str  # "agency" | "professional_services"


PORTFOLIO_CORPUS: tuple[PortfolioHost, ...] = (
    # --- Indian digital/web agencies (Clutch.co India digital-marketing directory) ---
    PortfolioHost("evendigit.com", "agency"),
    PortfolioHost("pagetraffic.com", "agency"),
    PortfolioHost("webspero.com", "agency"),
    PortfolioHost("conversionperk.com", "agency"),
    PortfolioHost("eintelligenceweb.com", "agency"),
    PortfolioHost("matrixbricks.com", "agency"),
    PortfolioHost("seotechexperts.com", "agency"),
    PortfolioHost("elsner.com", "agency"),
    PortfolioHost("seotonic.com", "agency"),
    PortfolioHost("futureprofilez.com", "agency"),
    PortfolioHost("esearchlogix.com", "agency"),
    PortfolioHost("skynettechnologies.com", "agency"),
    PortfolioHost("uncannycs.com", "agency"),
    PortfolioHost("3mindsdigital.com", "agency"),
    PortfolioHost("ikf.co.in", "agency"),
    PortfolioHost("offshoremarketers.com", "agency"),
    PortfolioHost("marastu.com", "agency"),
    PortfolioHost("tuesday.is", "agency"),
    PortfolioHost("ptiwebtech.com", "agency"),
    PortfolioHost("dcrayon.com", "agency"),
    PortfolioHost("tikdi.in", "agency"),
    PortfolioHost("trooinbound.com", "agency"),
    PortfolioHost("kloctechnologies.com", "agency"),
    PortfolioHost("thecssagency.com", "agency"),
    PortfolioHost("growthmak.com", "agency"),
    PortfolioHost("amwebinsights.com", "agency"),
    PortfolioHost("taskvirtual.com", "agency"),
    PortfolioHost("ivalueplus.com", "agency"),
    PortfolioHost("krishangtechnolab.com", "agency"),
    PortfolioHost("brainwavesindia.com", "agency"),
    # --- Indian chartered accountancy / professional services firms ---
    PortfolioHost("angca.com", "professional_services"),
    PortfolioHost("kdpaccountants.com", "professional_services"),
    PortfolioHost("masllp.com", "professional_services"),
    PortfolioHost("neerajbhagat.com", "professional_services"),
    PortfolioHost("hcoca.com", "professional_services"),
    PortfolioHost("singhico.com", "professional_services"),
    PortfolioHost("asa.in", "professional_services"),
    PortfolioHost("dpncindia.com", "professional_services"),
    PortfolioHost("sskmin.com", "professional_services"),
    PortfolioHost("trchadha.com", "professional_services"),
    PortfolioHost("cnkindia.com", "professional_services"),
    PortfolioHost("sharpandtannan.com", "professional_services"),
    PortfolioHost("dhc.co.in", "professional_services"),
    PortfolioHost("mahajanaibara.com", "professional_services"),
    PortfolioHost("knavcpa.com", "professional_services"),
    PortfolioHost("pkfindia.in", "professional_services"),
    PortfolioHost("nashah.com", "professional_services"),
    PortfolioHost("lodhaco.com", "professional_services"),
    PortfolioHost("scvindia.com", "professional_services"),
    PortfolioHost("srdinodia.com", "professional_services"),
)

assert len(PORTFOLIO_CORPUS) == 50
assert len({h.hostname for h in PORTFOLIO_CORPUS}) == 50, "duplicate hostname in corpus"
