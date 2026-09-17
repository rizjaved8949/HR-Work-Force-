"""Generate the checked Step-3 current-data mapping from the supplied Data/*.csv files.

The generator is deterministic and conservative: only ontology source-field hints
or file-context overrides become semantic property mappings. Unknown columns are
classified, never guessed into an ontology property.
"""
from __future__ import annotations

import csv, json
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'Data'
ONTOLOGY_FILE=ROOT/'backend'/'ontology'/'hr_ontology_v1.json'
OUT=Path(__file__).resolve().parent/'definitions'/'current_data_mappings.json'
REL=Path(__file__).resolve().parent/'definitions'/'relationship_rules.json'

CONTEXT_OVERRIDES={
 ('Organization_Master.csv','Currency'):'Organization.currency',
 ('Cost_Center_Master.csv','Currency'):'CostCenter.currency',
 ('Business_Unit_Master.csv','Active_Status'):'BusinessUnit.activeStatus',
 ('Department_Master.csv','Active_Status'):'Department.activeStatus',
 ('Organizational_Unit_Master.csv','Active_Status'):'OrganizationalUnit.activeStatus',
 ('Cost_Center_Master.csv','Active_Status'):'CostCenter.activeStatus',
 ('Learning_Course_Catalog.csv','Active_Status'):'LearningCourse.activeStatus',
 ('Business_Unit_Master.csv','Effective_Start_Date'):'BusinessUnit.effectiveStartDate',
 ('Business_Unit_Master.csv','Effective_End_Date'):'BusinessUnit.effectiveEndDate',
 ('Department_Master.csv','Effective_Start_Date'):'Department.effectiveStartDate',
 ('Department_Master.csv','Effective_End_Date'):'Department.effectiveEndDate',
 ('Cost_Center_Master.csv','Effective_Start_Date'):'CostCenter.effectiveStartDate',
 ('Cost_Center_Master.csv','Effective_End_Date'):'CostCenter.effectiveEndDate',
 ('Position_Master.csv','Employment_Type'):'Position.employmentType',
 ('Position_Requirements.csv','Employment_Type'):'Position.employmentType',
 ('Employee_Profile.csv','Employment_Type'):'Employment.employmentType',
 ('Employee_Assignment_History.csv','Employment_Type'):'Employment.employmentType',
 ('Final_Attrition_Dataset_200_Employees.csv','Employment_Type'):'Employment.employmentType',
 ('Position_Master.csv','Job_Level'):'Position.jobLevel',
 ('Position_Requirements.csv','Job_Level'):'Position.jobLevel',
 ('Simulation/Simulation_Position_Business_Evaluation.csv','Job_Level'):'Position.jobLevel',
 ('Employee_Profile.csv','Job_Level'):'Employment.jobLevel',
 ('Employee_Experience.csv','Job_Level'):'Employment.jobLevel',
 ('Employee_Performance.csv','Job_Level'):'Employment.jobLevel',
 ('Employee_Performance_Summary.csv','Job_Level'):'Employment.jobLevel',
 ('Employee_Performance_Monthly.csv','Job_Level'):'Employment.jobLevel',
 ('Employee_Performance_Evidence_Monthly.csv','Job_Level'):'Employment.jobLevel',
 ('Employee_KPI_Assignment.csv','Job_Level'):'Employment.jobLevel',
 ('Performance_Role_Mapping.csv','Job_Level'):'Employment.jobLevel',
 ('Final_Attrition_Dataset_200_Employees.csv','Job_Level'):'Employment.jobLevel',
 ('Position_Master.csv','Headcount_Inclusion_Category'):'Position.headcountInclusionCategory',
 ('Employee_Profile.csv','Headcount_Inclusion_Category'):'Employment.headcountInclusionCategory',
 ('Final_Attrition_Dataset_200_Employees.csv','Headcount_Inclusion_Category'):'Employment.headcountInclusionCategory',
 ('Department_Budget.csv','Budget_Currency'):'DepartmentBudget.currency',
 ('Position_Budget.csv','Budget_Currency'):'PositionBudget.currency',
 ('Employee_Performance_Evidence_Monthly.csv','Performance_Month'):'PerformanceEvidence.performanceMonth',
 ('Employee_Performance_Monthly.csv','Performance_Month'):'PerformanceRecord.assessmentPeriod',
 ('Employee_Performance_Summary.csv','Latest_Performance_Score'):'PerformanceSummary.latestPerformanceScore',
 ('Employee_Learning_Profile_Summary.csv','Latest_Performance_Score'):'PerformanceSummary.latestPerformanceScore',
 ('Employee_Development_Recommendation.csv','Latest_Performance_Score'):'PerformanceSummary.latestPerformanceScore',
 ('Employee_Performance_Summary.csv','Latest_Performance_Band'):'PerformanceSummary.latestPerformanceBand',
 ('Employee_Learning_Profile_Summary.csv','Latest_Performance_Band'):'PerformanceSummary.latestPerformanceBand',
 ('Employee_Development_Recommendation.csv','Latest_Performance_Band'):'PerformanceSummary.latestPerformanceBand',
 ('KPI_Catalog.csv','Measurement_Unit'):'KPI.measurementUnit',
 ('Employee_Performance_Evidence_Monthly.csv','Measurement_Unit'):'KPI.measurementUnit',
 ('Workforce_Demand_Drivers.csv','Measurement_Unit'):'WorkforceDemandDriver.measurementUnit',
 ('Employee_Skills.csv','Certification_Status'):'EmployeeSkill.certificationStatus',
 ('Employee_Learning_History.csv','Certification_Status'):'LearningRecord.certificationStatus',
 ('Position_Requirements.csv','Minimum_Proficiency_Level'):'PositionRequirement.minimumProficiencyLevel',
 ('Position_Skill_Requirements.csv','Minimum_Proficiency_Level'):'PositionSkillRequirement.minimumProficiencyLevel',
 ('Monthly_Headcount_Snapshot.csv','Snapshot_Month'):'HeadcountSnapshot.snapshotMonth',
 ('Workforce_Demand_Drivers.csv','Snapshot_Month'):'WorkforceDemandDriver.snapshotMonth',
 ('Daily_Headcount_Activity.csv','Actual_Employee_Count'):'DailyWorkforceActivity.actualEmployeeCount',
 ('Monthly_Headcount_Snapshot.csv','Actual_Employee_Count'):'HeadcountSnapshot.actualEmployeeCount',
 ('Current_Headcount_Summary.csv','Actual_Employee_Count'):'HeadcountSnapshot.actualEmployeeCount',
 ('Department_Budget.csv','Budgeted_Position_Count'):'DepartmentBudget.budgetedPositionCount',
 ('Monthly_Headcount_Snapshot.csv','Budgeted_Position_Count'):'HeadcountSnapshot.budgetedPositionCount',
 ('Current_Headcount_Summary.csv','Budgeted_Position_Count'):'HeadcountSnapshot.budgetedPositionCount',
 ('Department_Master.csv','Budgeted_Position_Count'):'HeadcountSnapshot.budgetedPositionCount',
 ('Department_Budget.csv','Budget_Status'):'DepartmentBudget.budgetStatus',
 ('Position_Budget.csv','Budget_Status'):'PositionBudget.budgetStatus',
 ('Headcount_Exception_Register.csv','Severity'):'HeadcountException.severity',
 ('Headcount_Exception_Register.csv','Threshold_Value'):'HeadcountException.thresholdValue',
 ('Headcount_Management_Rules.csv','Severity'):'DecisionRule.severity',
 ('Headcount_Management_Rules.csv','Threshold_Value'):'DecisionRule.thresholdValue',
 ('HR_Decision_Cases.csv','id'):'DecisionCase.caseId',
 ('HR_Decision_Cases.csv','case_key'):'DecisionCase.caseKey',
 ('HR_Decision_Cases.csv','case_type'):'DecisionCase.caseType',
 ('HR_Decision_Cases.csv','title'):'DecisionCase.title',
 ('HR_Decision_Cases.csv','status'):'DecisionCase.status',
 ('HR_Decision_Cases.csv','priority'):'DecisionCase.priority',
 ('HR_Decision_Cases.csv','reason'):'DecisionCase.reason',
 ('HR_Decision_Cases.csv','suggested_action'):'DecisionCase.suggestedAction',
 ('HR_Decision_Cases.csv','detected_at'):'DecisionCase.detectedAt',
 ('HR_Decision_Cases.csv','data_as_of'):'DecisionCase.dataAsOf',
 ('HR_Decision_Cases.csv','is_trigger_active'):'DecisionCase.isTriggerActive',
 ('HR_Decision_Cases.csv','evidence_json'):'DecisionCase.evidence',
}

DATA_AS_OF_TARGETS={
 'Employee_Profile.csv':'Employment.dataAsOfDate','Final_Attrition_Dataset_200_Employees.csv':'EngagementRecord.dataAsOfDate',
 'Employee_Experience.csv':'ExperienceProfile.totalExperienceYears', # special: no as-of prop on ExperienceProfile
 'Employee_Performance.csv':'PerformanceRecord.dataAsOfDate','Employee_Performance_Summary.csv':'PerformanceSummary.dataAsOfDate',
 'Employee_Performance_Evidence_Monthly.csv':'PerformanceEvidence.dataAsOfDate','Employee_Attendance.csv':'AttendanceRecord.dataAsOfDate',
 'Employee_Skills.csv':'EmployeeSkill.dataAsOfDate','Position_Requirements.csv':'PositionRequirement.dataAsOfDate',
 'Position_Skill_Requirements.csv':'PositionSkillRequirement.dataAsOfDate','Learning_Course_Catalog.csv':'LearningCourse.dataAsOfDate',
 'Employee_Learning_History.csv':'LearningRecord.dataAsOfDate','Position_Vacancy_History.csv':'VacancyRecord.dataAsOfDate',
 'Current_Headcount_Summary.csv':'HeadcountSnapshot.dataAsOfDate','Monthly_Headcount_Snapshot.csv':'HeadcountSnapshot.dataAsOfDate',
 'Department_Budget.csv':'DepartmentBudget.dataAsOfDate','Position_Budget.csv':'PositionBudget.dataAsOfDate',
 'Workforce_Demand_Drivers.csv':'WorkforceDemandDriver.dataAsOfDate','Employee_Assignment_History.csv':'Assignment.dataAsOfDate',
}
# Remove files for which there is no faithful as-of target in ontology.
DATA_AS_OF_TARGETS.pop('Employee_Experience.csv',None)

RELATIONSHIP_COLUMNS={
 'Business_Unit_Leader_Position_ID','Budget_Owner_Employee_ID','Parent_Department_ID','Department_Head_Position_ID',
 'Primary_Work_Location_ID','Manager_Employee_ID','Parent_Organizational_Unit_ID','Reporting_Position_ID',
 'Current_Employee_ID','rule_id','employee_id','position_id','department_id','subject_id','From_Department_ID','To_Department_ID','From_Organizational_Unit_ID','To_Organizational_Unit_ID',
 'From_Position_ID','To_Position_ID'
}
TRAINING_REFERENCE={'Will_Resign_in_Next_6_Months','Attrition_Label_Reference','Expected_Employee_Exit_Count_from_Labels'}
OPERATIONAL_FILES={
 'Performance_Data_Package_Manifest.csv','Performance_Data_Quality_Report.csv','Learning_Data_Package_Manifest.csv','Learning_Data_Quality_Report.csv',
 'HR_Decision_Data_Source_Map.csv','HR_Decision_Trigger_Config.csv','Headcount_Management_Metric_Definitions.csv'
}
OPERATIONAL_COLUMNS={
 'Existing_Source_Fields_Used','Production_Replacement_Source','Manager_Verification_Status','Calculation_Status','Calculation_Version',
 'Assignment_Source','History_Basis','Record_Source','Is_Actual_LMS_Record','Catalog_Mode','Mapping_Status','Evidence_Mode','Operational_Context',
 'Dataset_Purpose','Synthetic_Data_Indicator','Record_Purpose','Employee_Record_Availability','Source_System','Data_Pattern_Description',
 'Primary_Existing_Extracts','New_Business_Evaluation_File','Example_HR_Question','File_Name','Row_Count','Purpose','Primary_Source_Data','Storage_Location',
 'Existing_Source_Files_Modified','Existing_File_Overwritten','Data_Folder','Validation_Check','Expected','Actual','Status','Detail','Check_ID','Check_Name','Expected_Value','Actual_Value','Notes',
 'Definition','Calculation_Logic','Primary_Source_Table','CSV_File','Supabase_Table','Dataset_Key','Source_Files','Source_Rule_ID','Aggregation_Mode'
}
DERIVED_AGGREGATE_HINTS={
 'Current_Employee_Count','Employee_Count','Average_Performance_Score','Median_Performance_Score','Maximum_Performance_Score','Exceptional_Count','Strong_Count',
 'Meets_Expectations_Count','Partially_Meets_Count','Improvement_Required_Count','Critical_KPI_Breach_Count','KPI_Count','Total_KPI_Weight_pct',
 'Calculated_Score_Before_Rules','Critical_KPI_Breach_Flag','Completed_Course_Count','Position_Skill_Gap_Count','Mandatory_Skill_Gap_Count','Recommended_Course_Count',
 'Top_Recommended_Course_ID','Top_Recommended_Course_Name','Top_Recommendation_Priority','Top_Recommendation_Basis','Learning_Development_Status',
 'Positions_Vacant_More_Than_90_Days','Critical_or_High_Priority_Open_Positions','Monthly_Salary_Cost','Monthly_Benefits_Cost','Approved_Monthly_People_Budget','Budget_Variance_Amount',
 'Strongest_KPI_1','Strongest_KPI_1_Score','Strongest_KPI_2','Strongest_KPI_2_Score','Development_KPI_1','Development_KPI_1_Score','Development_KPI_2','Development_KPI_2_Score',
 'Existing_Performance_Score_Reference','Existing_Performance_Band_Reference','Priority_Score','Recommendation_Rank'
}

# Dataset/column classifications that are intentionally outside scalar ontology properties.
ANALYTICAL_PAYLOAD_FILES={"Employee_Development_Recommendation.csv","Employee_Learning_Profile_Summary.csv","Department_Performance_Monthly.csv"}
SERVICE_CONFIG_FILES={"Performance_Cycle.csv","Employee_KPI_Assignment.csv","Performance_Role_Mapping.csv","Role_KPI_Template.csv","Headcount_Management_Rules.csv","HR_Decision_Trigger_Rules.csv"}
ARCHIVAL_FILES={"Historical_Employee_Register.csv"}
DESCRIPTIVE_FILES={"KPI_Catalog.csv","KPI_Skill_Development_Map.csv","Skill_Course_Mapping.csv"}
DENORMALIZED_LABELS={"Reporting_Title","Current_Employee_Name","From_Department_Name","To_Department_Name","Required_Skills_Summary","Preferred_Skills_Summary"}

SIMULATION_WIDE_FILES={
 'Simulation/Simulation_Employee_Features.csv','Simulation/Simulation_Department_Business_Evaluation.csv',
 'Simulation/Simulation_Position_Business_Evaluation.csv','Simulation/Simulation_Learning_Business_Evaluation.csv'
}


def load_ontology(): return json.loads(ONTOLOGY_FILE.read_text(encoding='utf-8'))

def field_index(o):
    idx=defaultdict(list)
    for e in o['entities']:
        for p in e.get('properties',[]):
            for f in p.get('current_source_fields',[]): idx[f].append(f"{e['name']}.{p['name']}")
    return idx

def classify(rel,col,candidates):
    key=(rel,col)
    if key in CONTEXT_OVERRIDES:
        return {'disposition':'context_property','ontology_path':CONTEXT_OVERRIDES[key],'transform':'identity'}
    if col=='Data_As_Of_Date' and rel in DATA_AS_OF_TARGETS:
        return {'disposition':'context_property','ontology_path':DATA_AS_OF_TARGETS[rel],'transform':'parse_date'}
    if len(candidates)==1:
        return {'disposition':'direct_property','ontology_path':candidates[0],'transform':'identity'}
    if col in RELATIONSHIP_COLUMNS:
        return {'disposition':'relationship_reference','reason':'Foreign/reference key used by an explicit relationship rule; not flattened into a fake scalar property.'}
    if col in TRAINING_REFERENCE:
        return {'disposition':'training_or_reference_label','reason':'Reference/training label, not a runtime business fact required by the current prediction contract.'}
    if rel in SIMULATION_WIDE_FILES:
        if col in {'Employee_ID','Department_ID','Position_ID','Course_ID','Employee_Name','Department_Name','Position_Title','Course_Name','Job_Level'}:
            return {'disposition':'context_identifier','reason':'Scope identifier/label for normalized scenario assumptions.'}
        if col in {'Assumption_Status','Assumption_Effective_Date','Feature_Source','Simulation_Feature_Version','Source_Data_As_Of_Date'}:
            # updated ontology hints may have caught some; this is safe fallback
            return {'disposition':'scenario_assumption_metadata','reason':'Metadata/provenance for normalized ScenarioAssumption records.'}
        return {'disposition':'scenario_assumption_value','reason':'Wide simulation-specific value; normalize to ScenarioAssumption.assumptionName/numericValue/unit scoped to its employee/department/position/course.'}
    if rel == 'Headcount_Scenario_Assumptions.csv':
        if col in {'Scenario_Assumption_ID','Scenario_Description','Assumption_Source','Data_As_Of_Date'}:
            return {'disposition':'scenario_assumption_metadata','reason':'Metadata for a wide headcount scenario assumption record.'}
        return {'disposition':'scenario_assumption_value','reason':'Normalize the wide scenario parameter to ScenarioAssumption.assumptionName/numericValue/unit.'}
    if rel in ANALYTICAL_PAYLOAD_FILES:
        return {'disposition':'analytical_or_derived_output','reason':'Precomputed analytical/learning output; graph migration must reproduce or materialize this output, not reinterpret it as a base HR fact.'}
    if rel in SERVICE_CONFIG_FILES:
        return {'disposition':'service_configuration','reason':'Configuration/effective-dating metadata used by the current service; keep in configuration/semantic layer rather than inventing a business fact.'}
    if rel in ARCHIVAL_FILES:
        return {'disposition':'archival_snapshot','reason':'Historical register field retained as archival history; current headcount runtime does not consume it beyond repository validation.'}
    if rel in DESCRIPTIVE_FILES:
        return {'disposition':'descriptive_or_relationship_metadata','reason':'Descriptive/mapping metadata not required as a scalar ontology fact by current scoring logic.'}
    if col in DENORMALIZED_LABELS:
        return {'disposition':'denormalized_label','reason':'Human-readable label derivable through an ID relationship; avoid duplicating it as a core graph fact.'}
    if rel in OPERATIONAL_FILES or col in OPERATIONAL_COLUMNS:
        return {'disposition':'operational_metadata','reason':'Implementation/manifest/quality/source metadata; retained outside the core business ontology.'}
    if col in DERIVED_AGGREGATE_HINTS:
        return {'disposition':'derived_aggregate','reason':'Precomputed/denormalized output that should be reproduced from graph facts or existing deterministic logic, not treated as a new base fact.'}
    if rel == 'Final_Attrition_Dataset_200_Employees.csv' and col in {'Commute_Minutes_One_Way','Manager_Changed_Last_6M'}:
        return {'disposition':'unused_source_fact','reason':'Present in source data but not consumed by the saved 14-feature CatBoost contract.'}
    if len(candidates)>1:
        return {'disposition':'context_not_scalar','reason':f'Context-dependent field is not safely representable as one scalar ontology property in this dataset: {candidates}'}
    return {'disposition':'explicitly_unmodeled_nonblocking','reason':'Source field is documented but is not required by the confirmed AI service contracts and is not guessed into ontology v1.'}

def build_relationships():
    rules=[
      ('business_unit_org','Business_Unit_Master.csv','Organization','HAS_BUSINESS_UNIT','BusinessUnit',['Organization_ID','Business_Unit_ID']),
      ('business_unit_leader','Business_Unit_Master.csv','BusinessUnit','LED_BY','Position',['Business_Unit_ID','Business_Unit_Leader_Position_ID']),
      ('department_bu','Department_Master.csv','BusinessUnit','HAS_DEPARTMENT','Department',['Business_Unit_ID','Department_ID']),
      ('department_parent','Department_Master.csv','Department','PARENT_OF','Department',['Parent_Department_ID','Department_ID']),
      ('department_head','Department_Master.csv','Department','LED_BY','Position',['Department_ID','Department_Head_Position_ID']),
      ('department_location','Department_Master.csv','Department','PRIMARY_LOCATION','WorkLocation',['Department_ID','Primary_Work_Location_ID']),
      ('department_cost_center','Department_Master.csv','Department','USES_COST_CENTER','CostCenter',['Department_ID','Cost_Center_ID']),
      ('org_unit_department','Organizational_Unit_Master.csv','Department','HAS_ORGANIZATIONAL_UNIT','OrganizationalUnit',['Department_ID','Organizational_Unit_ID']),
      ('org_unit_parent','Organizational_Unit_Master.csv','OrganizationalUnit','PARENT_OF','OrganizationalUnit',['Parent_Organizational_Unit_ID','Organizational_Unit_ID']),
      ('cost_center_department','Cost_Center_Master.csv','Department','USES_COST_CENTER','CostCenter',['Department_ID','Cost_Center_ID']),
      ('cost_center_owner','Cost_Center_Master.csv','CostCenter','BUDGET_OWNED_BY','Employee',['Cost_Center_ID','Budget_Owner_Employee_ID']),
      ('employee_reports_to','Employee_Profile.csv','Employee','REPORTS_TO','Employee',['Employee_ID','Manager_Employee_ID']),
      ('assignment_employee','Employee_Assignment_History.csv','Employee','HAS_ASSIGNMENT','Assignment',['Employee_ID','Assignment_ID']),
      ('assignment_position','Employee_Assignment_History.csv','Assignment','TO_POSITION','Position',['Assignment_ID','Position_ID']),
      ('assignment_department','Employee_Assignment_History.csv','Assignment','IN_DEPARTMENT','Department',['Assignment_ID','Department_ID']),
      ('assignment_org_unit','Employee_Assignment_History.csv','Assignment','IN_ORGANIZATIONAL_UNIT','OrganizationalUnit',['Assignment_ID','Organizational_Unit_ID']),
      ('assignment_location','Employee_Assignment_History.csv','Assignment','AT_LOCATION','WorkLocation',['Assignment_ID','Work_Location_ID']),
      ('assignment_cost_center','Employee_Assignment_History.csv','Assignment','CHARGED_TO','CostCenter',['Assignment_ID','Cost_Center_ID']),
      ('position_department','Position_Master.csv','Position','IN_DEPARTMENT','Department',['Position_ID','Department_ID']),
      ('position_reports','Position_Master.csv','Position','REPORTS_TO_POSITION','Position',['Position_ID','Reporting_Position_ID']),
      ('position_location','Position_Master.csv','Position','AT_LOCATION','WorkLocation',['Position_ID','Work_Location_ID']),
      ('position_cost_center','Position_Master.csv','Position','CHARGED_TO','CostCenter',['Position_ID','Cost_Center_ID']),
      ('movement_from_department','Workforce_Movement_History.csv','CareerMovement','FROM_DEPARTMENT','Department',['Movement_ID','From_Department_ID']),
      ('movement_to_department','Workforce_Movement_History.csv','CareerMovement','TO_DEPARTMENT','Department',['Movement_ID','To_Department_ID']),
      ('movement_from_position','Workforce_Movement_History.csv','CareerMovement','FROM_POSITION','Position',['Movement_ID','From_Position_ID']),
      ('movement_to_position','Workforce_Movement_History.csv','CareerMovement','TO_POSITION','Position',['Movement_ID','To_Position_ID']),
      ('decision_rule_case','HR_Decision_Cases.csv','DecisionRule','GENERATES_CASE','DecisionCase',['rule_id','id']),
      ('decision_case_employee','HR_Decision_Cases.csv','DecisionCase','ABOUT_EMPLOYEE','Employee',['id','employee_id']),
      ('decision_case_position','HR_Decision_Cases.csv','DecisionCase','ABOUT_POSITION','Position',['id','position_id']),
      ('decision_case_department','HR_Decision_Cases.csv','DecisionCase','ABOUT_DEPARTMENT','Department',['id','department_id']),
      ('sim_employee_scope','Simulation/Simulation_Employee_Features.csv','ScenarioAssumption','APPLIES_TO_EMPLOYEE','Employee',['Employee_ID']),
      ('sim_department_scope','Simulation/Simulation_Department_Business_Evaluation.csv','ScenarioAssumption','APPLIES_TO_DEPARTMENT','Department',['Department_ID']),
      ('sim_position_scope','Simulation/Simulation_Position_Business_Evaluation.csv','ScenarioAssumption','APPLIES_TO_POSITION','Position',['Position_ID']),
      ('sim_course_scope','Simulation/Simulation_Learning_Business_Evaluation.csv','ScenarioAssumption','APPLIES_TO_COURSE','LearningCourse',['Course_ID']),
    ]
    return {'version':'1.0.0-step3','rules':[{'id':i,'source_file':f,'source_entity':s,'relation':r,'target_entity':t,'required_columns':cols} for i,f,s,r,t,cols in rules]}

def main():
    o=load_ontology(); idx=field_index(o); datasets=[]
    for path in sorted(DATA.rglob('*.csv')):
        rel=path.relative_to(DATA).as_posix()
        with path.open(encoding='utf-8-sig',newline='') as h:
            reader=csv.reader(h); headers=next(reader,[]); rows=sum(1 for _ in reader)
        cols=[]
        for col in headers:
            item={'source_column':col, **classify(rel,col,idx.get(col,[]))}
            cols.append(item)
        datasets.append({'source_file':rel,'row_count':rows,'column_count':len(headers),'columns':cols})
    payload={
      'version':'1.0.0-step3','ontology_version':o['version'],'status':'current_data_mapping_complete_with_explicit_gaps',
      'principles':[
        'Every supplied CSV column is explicitly classified; unknown fields are never guessed into ontology paths.',
        'Relationship foreign keys are represented by relationship rules, not flattened as fake scalar properties.',
        'Precomputed aggregates are treated as derived outputs when graph facts can reproduce them.',
        'Simulation-wide values are normalized as scoped ScenarioAssumption records rather than adding dozens of one-off ontology properties.',
        'Training/reference labels are separated from runtime prediction inputs.'
      ],
      'datasets':datasets
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    REL.write_text(json.dumps(build_relationships(),indent=2),encoding='utf-8')

if __name__=='__main__': main()
