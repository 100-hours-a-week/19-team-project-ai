"""레포트 생성 라우터 - 11개 섹션 리포트"""

from fastapi import APIRouter, File, HTTPException, UploadFile

from controllers.repo_controller import get_repo_controller
from schemas.common import ApiResponse, ResponseCode
from schemas.repo import (
    ActionPlan,
    BasicInfo,
    CapabilityMatching,
    DataSources,
    FinalComment,
    ImprovementsAnalysis,
    JobParseRequest,
    JobParseResponse,
    OverallEvaluation,
    Reliability,
    ReportGenerateRequest,
    ReportGenerateResponse,
    RequirementComparison,
    StrengthsAnalysis,
    TechCoverage,
)

router = APIRouter(prefix="/repo", tags=["Report"])


# ============== 임시 이력서 저장소 (테스트용) ==============
_resume_store: dict[str, dict] = {}


@router.post("/resumes/upload", summary="[테스트용] 이력서 업로드")
async def upload_resume_for_test(file: UploadFile = File(...)):
    """테스트용 이력서 업로드 엔드포인트

    PDF 파일을 업로드하면 파싱 후 임시 저장합니다.
    반환된 resume_id를 /repo/generate에서 사용할 수 있습니다.
    """
    from controllers.resumes_controller import get_resumes_controller

    pdf_bytes = await file.read()
    controller = get_resumes_controller()
    resume_id = len(_resume_store) + 1

    result = await controller.parse_resume_from_bytes(
        resume_id=resume_id,
        pdf_bytes=pdf_bytes,
        enable_pii_masking=True,
    )

    if result.status.value == "COMPLETED" and result.result:
        resume_data = {
            "resume_id": str(resume_id),
            "title": result.result.content_json.work_experience[0] if result.result.content_json.work_experience else "이력서",
            "work_experience": [str(exp) for exp in result.result.content_json.work_experience],
            "projects": [str(proj) for proj in result.result.content_json.projects],
            "education": result.result.content_json.education,
            "certifications": result.result.content_json.certifications,
            "etc": result.result.content_json.etc,
        }
        _resume_store[str(resume_id)] = resume_data

        return ApiResponse(
            code=ResponseCode.OK,
            data={"resume_id": str(resume_id), "status": "uploaded", "parsed_fields": resume_data},
        )

    return ApiResponse(
        code=ResponseCode.INTERNAL_SERVER_ERROR,
        data={"error": result.error.detail if result.error else "파싱 실패"},
    )


@router.post("/job", response_model=ApiResponse[JobParseResponse])
async def parse_job(request: JobParseRequest):
    """채용공고 파싱 (URL 또는 텍스트)"""
    if not request.job_url and not request.job_text:
        raise HTTPException(
            status_code=400,
            detail={"code": ResponseCode.BAD_REQUEST.value, "data": "job_url 또는 job_text 필수"},
        )

    controller = get_repo_controller()
    result = await controller.parse_job(request)

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail={"code": ResponseCode.INTERNAL_SERVER_ERROR.value, "data": result.get("error")},
        )

    data = result.get("data", {})
    return ApiResponse(
        code=ResponseCode.OK,
        data=JobParseResponse(
            job_id=result.get("job_id", ""),
            title=data.get("title"),
            company=data.get("company"),
            department=data.get("department"),
            employment_type=data.get("employment_type"),
            experience_required=data.get("experience_required"),
            education_required=data.get("education_required"),
            requirements=data.get("requirements", []),
            preferences=data.get("preferences", []),
            tech_stack=data.get("tech_stack", []),
            responsibilities=data.get("responsibilities", []),
        ),
    )


@router.post("/generate", response_model=ApiResponse[ReportGenerateResponse])
async def generate_report(request: ReportGenerateRequest):
    """리포트 생성 - 11개 섹션

    현직자 피드백 + AI 분석을 통합하여 리포트를 생성합니다.

    - **resume_id**: 이력서 ID (필수)
    - **job_url**: 채용공고 URL (필수)
    - **mentor_feedback**: 현직자 피드백 (선택)
    - **chat_messages**: 채팅 메시지 (선택)
    """
    if not request.job_url and not request.job_text:
        raise HTTPException(
            status_code=400,
            detail={"code": ResponseCode.BAD_REQUEST.value, "data": "job_url은 필수입니다"},
        )

    controller = get_repo_controller()

    # resume_id로 저장된 이력서 데이터 조회
    resume_data = _resume_store.get(request.resume_id)
    if not resume_data:
        resume_data = {
            "title": "이력서",
            "work_experience": [],
            "projects": [],
            "education": [],
            "certifications": [],
            "skills": [],
        }

    # user_skills가 제공되면 resume_data에 추가
    if request.user_skills:
        resume_data["skills"] = request.user_skills

    result = await controller.generate_report(request, resume_data)


    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail={"code": ResponseCode.INTERNAL_SERVER_ERROR.value, "data": result.get("error")},
        )

    report_data = result.get("report_data", {})

    return ApiResponse(
        code=ResponseCode.OK,
        data=ReportGenerateResponse(
            report_id=result.get("report_id", ""),
            resume_id=request.resume_id,
            basic_info=BasicInfo(**report_data.get("basic_info", {})),
            requirement_comparison=RequirementComparison(**report_data.get("requirement_comparison", {})),
            tech_coverage=TechCoverage(**report_data.get("tech_coverage", {})),
            capability_matching=CapabilityMatching(**report_data.get("capability_matching", {})),
            strengths_analysis=StrengthsAnalysis(**report_data.get("strengths_analysis", {})),
            improvements_analysis=ImprovementsAnalysis(**report_data.get("improvements_analysis", {})),
            action_plan=ActionPlan(**report_data.get("action_plan", {})),
            overall_evaluation=OverallEvaluation(**report_data.get("overall_evaluation", {})),
            final_comment=FinalComment(**report_data.get("final_comment", {})),
            data_sources=DataSources(**report_data.get("data_sources", {})),
            reliability=Reliability(**report_data.get("reliability", {})),
            processing_time_ms=result.get("processing_time_ms"),
        ),
    )


@router.get("/{report_id}", response_model=ApiResponse[ReportGenerateResponse])
async def get_report(report_id: str):
    """리포트 조회"""
    controller = get_repo_controller()
    result = await controller.get_report(report_id)

    if not result:
        raise HTTPException(
            status_code=404,
            detail={"code": ResponseCode.NOT_FOUND.value, "data": {"resource": "report", "id": report_id}},
        )

    report_data = result.get("report_data", {})

    return ApiResponse(
        code=ResponseCode.OK,
        data=ReportGenerateResponse(
            report_id=result.get("report_id", ""),
            resume_id=result.get("resume_id", ""),
            basic_info=BasicInfo(**report_data.get("basic_info", {})),
            requirement_comparison=RequirementComparison(**report_data.get("requirement_comparison", {})),
            tech_coverage=TechCoverage(**report_data.get("tech_coverage", {})),
            capability_matching=CapabilityMatching(**report_data.get("capability_matching", {})),
            strengths_analysis=StrengthsAnalysis(**report_data.get("strengths_analysis", {})),
            improvements_analysis=ImprovementsAnalysis(**report_data.get("improvements_analysis", {})),
            action_plan=ActionPlan(**report_data.get("action_plan", {})),
            overall_evaluation=OverallEvaluation(**report_data.get("overall_evaluation", {})),
            final_comment=FinalComment(**report_data.get("final_comment", {})),
            data_sources=DataSources(**report_data.get("data_sources", {})),
            reliability=Reliability(**report_data.get("reliability", {})),
        ),
    )
