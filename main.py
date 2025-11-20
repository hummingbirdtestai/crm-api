from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from supabase import create_client
import os
from datetime import datetime

# ---------------------------------------------------------
# INIT
# ---------------------------------------------------------
app = FastAPI(title="CRM API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ---------------------------------------------------------
# MODELS
# ---------------------------------------------------------
class FilterPayload(BaseModel):
    executive_id: str
    state: Optional[str] = None
    category: Optional[str] = None
    gender: Optional[str] = None
    status: Optional[str] = None
    bargain_type: Optional[str] = None
    min_heat: Optional[int] = None
    max_heat: Optional[int] = 100
    prospect_percent: Optional[int] = None
    sort_by: Optional[str] = None


class NotePayload(BaseModel):
    candidate_id: int
    executive_id: str
    note: str


class CallLogPayload(BaseModel):
    candidate_id: int
    executive_id: str
    type: str
    details: dict


class FollowPayload(BaseModel):
    candidate_id: int
    executive_id: str
    schedule_time: str


class StatusPayload(BaseModel):
    candidate_id: int
    executive_id: str
    status: str


class OfferSendPayload(BaseModel):
    candidate_id: int
    executive_id: str
    offer_id: str


class BulkAssignPayload(BaseModel):
    assign_from: str
    assign_to: str
    candidate_ids: List[int]
    reason: Optional[str] = None


# ---------------------------------------------------------
# AUTH / PROFILE
# ---------------------------------------------------------
@app.get("/auth/profile")
def get_profile(phone: str):
    res = (
        supabase
        .from_("db_executives")
        .select("*")
        .eq("mobile", phone)
        .maybe_single()
        .execute()
    )
    return res.data or {}


# ---------------------------------------------------------
# EXECUTIVE DASHBOARD
# ---------------------------------------------------------
@app.get("/executive/dashboard")
def get_dashboard(executive_id: str):

    result = (
        supabase
        .from_("db_candidates")
        .select("*")
        .eq("executive_id", executive_id)
        .execute()
    )

    data = result.data or []

    hot = len([x for x in data if x.get("lead_heat_score", 0) >= 70])
    fresh = len([x for x in data if x.get("lead_status") == "fresh"])
    bargaining = len([x for x in data if x.get("lead_status") == "bargaining"])

    today = datetime.now().strftime("%Y-%m-%d")
    follow_up_today = len([
        x for x in data
        if x.get("follow_up_at") and str(x["follow_up_at"]).startswith(today)
    ])

    return {
        "summary": {
            "total_assigned": len(data),
            "hot_leads": hot,
            "followups_today": follow_up_today,
            "fresh": fresh,
            "bargainers": bargaining
        }
    }


# ---------------------------------------------------------
# EXECUTIVE LEAD LIST (GET)
# ---------------------------------------------------------
@app.get("/executive/leads")
def lead_list_get(
    executive_id: str,
    status: Optional[str] = None,
    heat_min: Optional[int] = None,
    follow_up_due: Optional[str] = None,
    sort: Optional[str] = None
):
    query = (
        supabase
        .from_("db_candidates")
        .select("*")
        .eq("executive_id", executive_id)
    )

    if status:
        query = query.eq("lead_status", status)

    if heat_min:
        query = query.gte("lead_heat_score", heat_min)

    if follow_up_due == "today":
        today = datetime.now().strftime("%Y-%m-%d")
        query = query.like("follow_up_at", f"{today}%")

    res = query.execute()
    leads = res.data or []

    # Sorting (fallback: by created_at)
    if sort == "newest":
        leads = sorted(leads, key=lambda x: x.get("created_at", ""), reverse=True)

    return {
        "executive_id": executive_id,
        "lead_count": len(leads),
        "leads": leads
    }


# ---------------------------------------------------------
# EXECUTIVE FILTERED LEAD LIST (POST)
# ---------------------------------------------------------
@app.post("/executive/leads")
def lead_list_post(payload: FilterPayload):
    rpc = (
        supabase
        .rpc("get_leads_filtered", {
            "p_executive_id": payload.executive_id,
            "p_state": payload.state,
            "p_category": payload.category,
            "p_gender": payload.gender,
            "p_status": payload.status,
            "p_bargain": payload.bargain_type,
            "p_min_heat": payload.min_heat,
            "p_max_heat": payload.max_heat
        })
        .execute()
    )

    leads = rpc.data or []

    if payload.sort_by == "newest":
        leads = sorted(leads, key=lambda x: x.get("created_at", ""), reverse=True)

    return {
        "executive_id": payload.executive_id,
        "lead_count": len(leads),
        "leads": leads
    }


# ---------------------------------------------------------
# MANAGER VIEW EXECUTIVE → LEADS
# ---------------------------------------------------------
@app.get("/manager/executive/leads")
def manager_leads(executive_id: str):

    exec_profile = (
        supabase
        .from_("db_executives")
        .select("*")
        .eq("executive_id", executive_id)
        .maybe_single()
        .execute()
    )

    leads = (
        supabase
        .from_("db_candidates")
        .select("*")
        .eq("executive_id", executive_id)
        .execute()
    )

    return {
        "executive": {
            "name": exec_profile.data.get("name", ""),
            "assigned_count": len(leads.data or [])
        },
        "leads": leads.data or []
    }


# ---------------------------------------------------------
# LEAD DETAIL
# ---------------------------------------------------------
@app.get("/lead/detail")
def lead_detail(id: int):
    cand = (
        supabase
        .from_("db_candidates")
        .select("*")
        .eq("id", id)
        .maybe_single()
        .execute()
    )

    timeline = supabase.rpc("get_timeline", {"p_candidate_id": id}).execute()
    offers = supabase.rpc("get_offers_for_candidate", {"p_candidate_id": id}).execute()

    return {
        "candidate": cand.data,
        "timeline": timeline.data,
        "offers": offers.data
    }


# ---------------------------------------------------------
# LOG CALL
# ---------------------------------------------------------
@app.post("/lead/call-log")
def log_call(payload: CallLogPayload):

    supabase.rpc("log_call_rpc", {
        "p_candidate_id": payload.candidate_id,
        "p_exec": payload.executive_id,
        "p_type": payload.type,
        "p_details": payload.details
    }).execute()

    return {"status": "success"}


# ---------------------------------------------------------
# ADD NOTE
# ---------------------------------------------------------
@app.post("/lead/add-note")
def add_note(payload: NotePayload):

    supabase.from_("db_notes").insert({
        "candidate_id": payload.candidate_id,
        "executive_id": payload.executive_id,
        "note": payload.note
    }).execute()

    return {"status": "success"}


# ---------------------------------------------------------
# FOLLOW-UP SCHEDULING
# ---------------------------------------------------------
@app.post("/lead/schedule-followup")
def schedule_followup(payload: FollowPayload):

    supabase.rpc("schedule_followup", {
        "p_candidate_id": payload.candidate_id,
        "p_exec": payload.executive_id,
        "p_time": payload.schedule_time
    }).execute()

    return {"status": "success"}


# ---------------------------------------------------------
# UPDATE STATUS
# ---------------------------------------------------------
@app.post("/lead/update-status")
def update_status(payload: StatusPayload):

    supabase.rpc("update_lead_status", {
        "p_candidate_id": payload.candidate_id,
        "p_status": payload.status,
        "p_exec": payload.executive_id
    }).execute()

    return {"status": "success"}


# ---------------------------------------------------------
# SEND OFFER
# ---------------------------------------------------------
@app.post("/offers/send")
def send_offer(payload: OfferSendPayload):

    supabase.rpc("record_offer_sent", {
        "p_candidate_id": payload.candidate_id,
        "p_exec": payload.executive_id,
        "p_offer": payload.offer_id
    }).execute()

    return {"status": "success"}


# ---------------------------------------------------------
# TIMELINE
# ---------------------------------------------------------
@app.get("/lead/timeline")
def timeline(candidate_id: int):
    res = supabase.rpc("get_timeline", {"p_candidate_id": candidate_id}).execute()
    return res.data


# ---------------------------------------------------------
# BULK ASSIGN LEADS
# ---------------------------------------------------------
@app.post("/manager/assign-leads")
def assign_bulk(payload: BulkAssignPayload):

    for cid in payload.candidate_ids:
        supabase.rpc("assign_lead", {
            "p_candidate_id": cid,
            "p_assign_to": payload.assign_to,
            "p_assign_from": payload.assign_from,
            "p_reason": payload.reason
        }).execute()

    return {"assigned": len(payload.candidate_ids)}


# ---------------------------------------------------------
# EXECUTIVE PERFORMANCE
# ---------------------------------------------------------
@app.get("/executive/performance")
def exec_perf(executive_id: str):

    calls = (
        supabase
        .from_("db_call_logs")
        .select("*")
        .eq("executive_id", executive_id)
        .execute()
    )

    offers = (
        supabase
        .from_("db_offers_sent")
        .select("*")
        .eq("executive_id", executive_id)
        .execute()
    )

    connected = len([c for c in calls.data if c["action_type"] == "connected"])
    not_lifted = len([c for c in calls.data if c["action_type"] == "not_lifted"])

    return {
        "calls": len(calls.data),
        "connected": connected,
        "not_lifted": not_lifted,
        "offers_sent": len(offers.data)
    }


# ---------------------------------------------------------
# STATE HEATMAP
# ---------------------------------------------------------
@app.get("/manager/state-heatmap")
def state_heatmap():
    out = supabase.rpc("state_heatmap").execute()
    return out.data or []


# ---------------------------------------------------------
# FOLLOWUP CALENDAR
# ---------------------------------------------------------
@app.get("/executive/followups")
def followups(executive_id: str, date: str):
    res = (
        supabase
        .from_("db_followups")
        .select("*")
        .eq("executive_id", executive_id)
        .like("follow_up_at", f"{date}%")
        .execute()
    )

    return res.data or []
