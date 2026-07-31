from __future__ import annotations


def _ratio_score(actual: float, required: float) -> float:
    if required <= 0:
        return 100.0
    return round(min(float(actual) / float(required), 1.0) * 100.0, 2)


class FeatureBuilder:
    """Converts raw employee evidence into comparable 0–100 features."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def build(
        self,
        candidate_profile: dict,
        position_context: dict,
        evidence: dict,
    ) -> dict:
        requirements = position_context["requirements"]
        required_skills = position_context["required_skills"]
        experience = evidence["experience"]
        performance = evidence["performance"]
        attendance = evidence["attendance"]

        skill_result = self._skill_match(
            required_skills=required_skills,
            employee_skills=evidence["skills"],
        )

        total_exp = _ratio_score(
            experience["Total_Experience_Years"],
            requirements["Minimum_Total_Experience_Years"],
        )
        relevant_exp = _ratio_score(
            experience["Relevant_Experience_Years"],
            requirements["Minimum_Relevant_Experience_Years"],
        )
        company_tenure = _ratio_score(
            experience["Tenure_Months"],
            requirements["Minimum_Company_Tenure_Months"],
        )

        leadership_required = (
            str(requirements["Leadership_Required"]).lower() == "yes"
        )
        if leadership_required:
            leadership_score = _ratio_score(
                experience["Leadership_Experience_Years"], 1.0
            )
        else:
            leadership_score = 100.0

        experience_score = round(
            total_exp * 0.35
            + relevant_exp * 0.45
            + company_tenure * 0.20,
            2,
        )

        readiness_map = self.config["readiness_mapping"]
        readiness = str(
            candidate_profile.get("Internal_Mobility_Readiness", "Not Ready")
        )
        readiness_score = float(readiness_map.get(readiness, 30))
        readiness_leadership_score = round(
            readiness_score * 0.70 + leadership_score * 0.30,
            2,
        )

        hard_checks = {
            "base_eligibility": (
                candidate_profile.get("Candidate_Base_Eligibility")
                == "Eligible"
            ),
            "minimum_total_experience": (
                float(experience["Total_Experience_Years"])
                >= float(requirements["Minimum_Total_Experience_Years"])
            ),
            "minimum_relevant_experience": (
                float(experience["Relevant_Experience_Years"])
                >= float(requirements["Minimum_Relevant_Experience_Years"])
            ),
            "minimum_company_tenure": (
                float(experience["Tenure_Months"])
                >= float(requirements["Minimum_Company_Tenure_Months"])
            ),
            "minimum_performance": (
                float(performance["Performance_Score"])
                >= float(requirements["Minimum_Performance_Score"])
            ),
            "minimum_attendance": (
                float(attendance["Attendance_Score"])
                >= float(requirements["Minimum_Attendance_Score"])
            ),
            "mandatory_skills": skill_result["mandatory_skills_met"],
            "leadership_requirement": (
                (not leadership_required)
                or float(experience["Leadership_Experience_Years"]) > 0
            ),
        }

        hard_gaps = [
            name for name, passed in hard_checks.items() if not passed
        ]

        return {
            **skill_result,
            "experience_score": experience_score,
            "performance_score": round(
                float(performance["Performance_Score"]), 2
            ),
            "attendance_score": round(
                float(attendance["Attendance_Score"]), 2
            ),
            "readiness_leadership_score": readiness_leadership_score,
            "hard_requirement_checks": hard_checks,
            "hard_requirement_gaps": hard_gaps,
            "hard_requirement_gap_count": len(hard_gaps),
            "source_readiness": readiness,
            "leadership_required": leadership_required,
            "leadership_experience_years": float(
                experience["Leadership_Experience_Years"]
            ),
        }

    @staticmethod
    def _skill_match(
        required_skills: list[dict],
        employee_skills: list[dict],
    ) -> dict:
        employee_lookup = {
            str(item["Skill_ID"]): item for item in employee_skills
        }

        weighted_score = 0.0
        total_weight = 0.0
        missing_skills: list[str] = []
        below_requirement_skills: list[str] = []
        matched_skills: list[str] = []
        mandatory_skills_met = True
        skill_details: list[dict] = []

        for requirement in required_skills:
            skill_id = str(requirement["Skill_ID"])
            skill_name = str(requirement["Skill_Name"])
            weight = float(requirement["Skill_Weight_pct"])
            total_weight += weight

            candidate_skill = employee_lookup.get(skill_id)
            mandatory = (
                str(requirement["Mandatory_Flag"]).lower() == "yes"
            )

            if candidate_skill is None:
                skill_score = 0.0
                missing_skills.append(skill_name)
                if mandatory:
                    mandatory_skills_met = False
                skill_details.append({
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "required": True,
                    "candidate_has_skill": False,
                    "match_score": 0.0,
                    "mandatory": mandatory,
                })
                continue

            proficiency_actual = float(
                candidate_skill["Proficiency_Level"]
            )
            proficiency_required = float(
                requirement["Minimum_Proficiency_Level"]
            )
            skill_actual = float(candidate_skill["Skill_Score"])
            skill_required = float(requirement["Minimum_Skill_Score"])

            proficiency_ratio = min(
                proficiency_actual / max(proficiency_required, 1.0),
                1.0,
            )
            score_ratio = min(
                skill_actual / max(skill_required, 1.0),
                1.0,
            )
            match = round(
                (proficiency_ratio * 0.5 + score_ratio * 0.5) * 100,
                2,
            )
            weighted_score += match * (weight / 100.0)

            meets = (
                proficiency_actual >= proficiency_required
                and skill_actual >= skill_required
            )
            if meets:
                matched_skills.append(skill_name)
            else:
                below_requirement_skills.append(skill_name)
                if mandatory:
                    mandatory_skills_met = False

            skill_details.append({
                "skill_id": skill_id,
                "skill_name": skill_name,
                "candidate_has_skill": True,
                "candidate_proficiency": proficiency_actual,
                "required_proficiency": proficiency_required,
                "candidate_skill_score": skill_actual,
                "required_skill_score": skill_required,
                "match_score": match,
                "mandatory": mandatory,
                "meets_requirement": meets,
            })

        if total_weight and abs(total_weight - 100.0) > 0.01:
            weighted_score = weighted_score * (100.0 / total_weight)

        return {
            "skill_match_score": round(weighted_score, 2),
            "mandatory_skills_met": mandatory_skills_met,
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "below_requirement_skills": below_requirement_skills,
            "skill_details": skill_details,
        }
