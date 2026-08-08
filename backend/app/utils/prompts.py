def format_knowledge(knowledge) -> str:
    """
    Formats either:
    1. Shared intelligence dictionary (current pipeline)
    2. Tavily search result list (backward compatible)
    """

    if not knowledge:
        return "No research available."

    # Current pipeline (shared summaries)
    if isinstance(knowledge, dict):

        text = ""

        for category, summary in knowledge.items():
            text += f"""
==============================
{category.upper()}
==============================

{summary}

"""

        return text

    # Old Tavily format
    if isinstance(knowledge, list):

        text = ""

        for item in knowledge:

            text += f"""
Title: {item.get("title","")}

URL: {item.get("url","")}

Snippet:
{item.get("snippet","")}

----------------------------------------

"""

        return text

    # Fallback
    return str(knowledge)
    

def market_prompt(
    company_name: str,
    industry: str,
    target_market: str,
    knowledge,
) -> str:

    return f"""
You are a Senior Market Research Consultant.

Company:
{company_name}

Industry:
{industry}

Target Market:
{target_market}

Research:
{format_knowledge(knowledge)}

Analyze ONLY the supplied research.

Return ONLY valid JSON.

{{
    "market_size":"",
    "growth_rate":"",
    "trends":[],
    "opportunities":[],
    "risks":[],
    "recommended_services":[]
}}

No markdown.
JSON only.
"""


def competitor_prompt(
    company_name: str,
    industry: str,
    target_market: str,
    knowledge,
) -> str:

    return f"""
You are a Senior Competitive Intelligence Consultant.

Company:
{company_name}

Industry:
{industry}

Target Market:
{target_market}

Research:
{format_knowledge(knowledge)}

Analyze ONLY the supplied research.

Return ONLY valid JSON.

{{
    "top_competitors":[
        {{
            "name":"",
            "website":"",
            "strengths":[],
            "weaknesses":[]
        }}
    ],
    "market_gap":[],
    "pricing_insights":[],
    "recommendations":[]
}}

No markdown.
JSON only.
"""


def lead_prompt(
    company_name: str,
    industry: str,
    target_market: str,
    knowledge,
) -> str:

    return f"""
You are a Senior B2B Sales Intelligence Consultant.

Company:
{company_name}

Industry:
{industry}

Target Market:
{target_market}

Research:
{format_knowledge(knowledge)}

Identify companies most likely to purchase the company's services.

Return ONLY valid JSON.

{{
    "qualified_leads":[
        {{
            "company":"",
            "website":"",
            "industry":"",
            "estimated_size":"",
            "why_good_fit":"",
            "pain_points":[],
            "recommended_service":"",
            "priority":"High | Medium | Low"
        }}
    ]
}}

Rules:

- Recommend 5–10 companies.
- Explain why each company is a good fit.
- Infer likely pain points.
- Recommend the best matching service.

No markdown.
JSON only.
"""


def pricing_prompt(
    company_name,
    industry,
    knowledge,
):

    return f"""
You are a Senior Pricing Intelligence Consultant.

Company:
{company_name}

Industry:
{industry}

Research:
{format_knowledge(knowledge)}

Analyze competitor pricing.

Return ONLY JSON.

{{
    "pricing_models":[
        {{
            "company":"",
            "pricing_model":"",
            "estimated_price":"",
            "strengths":[],
            "weaknesses":[]
        }}
    ],

    "pricing_gaps":[
        ""
    ],

    "recommended_pricing_strategy":"",

    "premium_services":[
        ""
    ]
}}

Rules:

- Estimate pricing when unavailable.
- Explain reasoning.
- Recommend the best pricing strategy.

No markdown.
JSON only.
"""


def audit_prompt(
    company_name,
    website,
    analysis,
):

    return f"""
You are a Senior Website Audit Consultant.

Company:
{company_name}

Website:
{website}

Website Analysis:
{analysis}

Return ONLY JSON.

{{
    "overall_score":0,
    "seo_score":0,
    "performance_score":0,
    "ux_score":0,
    "strengths":[],
    "weaknesses":[],
    "critical_issues":[],
    "recommendations":[],
    "recommended_services":[]
}}

Scores must be between 0 and 100.

No markdown.
JSON only.
"""


def opportunity_prompt(
    company_name,
    market,
    competitors,
    leads,
    audit,
    pricing,
):

    return f"""
You are a Senior Business Growth Strategist.

Company:
{company_name}

Market Intelligence:
{market}

Competitor Analysis:
{competitors}

Lead Analysis:
{leads}

Website Audit:
{audit}

Pricing Intelligence:
{pricing}

Combine everything into one executive strategy.

Return ONLY JSON.

{{
    "business_summary":"",

    "top_opportunities":[
        ""
    ],

    "best_target_industries":[
        ""
    ],

    "highest_value_services":[
        {{
            "service":"",
            "reason":"",
            "demand":"High | Medium | Low"
        }}
    ],

    "competitive_advantages":[
        ""
    ],

    "highest_priority_leads":[
        {{
            "company":"",
            "reason":"",
            "priority":"High | Medium | Low"
        }}
    ],

    "estimated_project_value":"",

    "recommended_next_steps":[
        ""
    ]
}}

No markdown.
JSON only.
"""


def outreach_prompt(
    company_name,
    opportunity,
):

    return f"""
You are a Senior B2B Sales Consultant.

Company:
{company_name}

Business Intelligence:
{opportunity}

Generate personalized outreach.

Return ONLY JSON.

{{
    "emails":[
        {{
            "company":"",
            "subject":"",
            "body":""
        }}
    ],

    "linkedin_messages":[
        {{
            "company":"",
            "message":""
        }}
    ],

    "cold_call_script":""
}}

No markdown.
JSON only.
"""


def search_planner_prompt(
    company_name,
    industry,
    target_market,
):

    return f"""
You are a Senior Business Intelligence Search Planner.

Company:
{company_name}

Industry:
{industry}

Target Market:
{target_market}

Create ONLY the highest-value search queries.

Return ONLY JSON.

{{
    "market": [],
    "competitors": [],
    "pricing": [],
    "technology": [],
    "seo": [],
    "social": [],
    "leads": []
}}

Rules:

- 1 query for market
- 2 queries for competitors
- 1 query for pricing
- 1 query for technology
- 1 query for seo
- 1 query for social
- 1 query for leads

Every query should be highly specific and optimized for Tavily.

JSON only.
"""


def research_summary_prompt(category, knowledge):

    return f"""
You are a Senior Business Intelligence Research Summarizer.

Category:
{category}

Research:
{knowledge}

Summarize ONLY the supplied research.

Return ONLY JSON.

{{
    "summary":""
}}

Rules:

- Maximum 300 words.
- Remove duplicates.
- Keep only important facts.
- Do not invent information.

No markdown.
JSON only.
"""