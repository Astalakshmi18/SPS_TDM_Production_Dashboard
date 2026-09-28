import sys
import os
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import json
import datetime
from apps.mapping.engine import apply_mapping

latvia_config = {
    "project_name": {"mode": "cell", "sheet": "Version Control", "cell": "B1"},
    "branch": {"mode": "static", "value": "TDM"},
    "start_date": {"mode": "cell", "sheet": "Project Summary", "cell": "D1"},
    "end_date": {"mode": "cell", "sheet": "Project Summary", "cell": "F1"},
    "target": {"mode": "cell", "sheet": "Project Summary", "cell": "B2"},
    "delivered": {"mode": "cell", "sheet": "Project Summary", "cell": "B4"},
    "images": {"mode": "sum_column", "sheet": "Calculation", "column": "Total Image"},
    "language": {"mode": "cell", "sheet": "Calculation", "cell": "E2"},
    "event_type": {"mode": "cell", "sheet": "Project Insights", "cell": "A3"},
    "extra_fields": {
      "Volume Unit": {"mode": "cell", "sheet": "Project Summary", "cell": "C2"},
      "Days Gone": {"mode": "cell", "sheet": "Project Summary", "cell": "C4"},
      "Delivered % (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B5"},
      "Days Gone %": {"mode": "cell", "sheet": "Project Summary", "cell": "B6"},
      "Remaining Records (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B8"},
      "Remaining Days (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "C8"},
      "Total Duration (Days)": {"mode": "cell", "sheet": "Project Summary", "cell": "H1"}
    },
    "inventory_rows": {
      "sheet": "Inventory",
      "columns": {
        "file_name": "DGS No",
        "event_type": "Event Type",
        "language": "Language",
        "image_count": "# Images",
        "record_count": "Ven's Rec",
        "shipment_date": "Shipment"
      }
    },
    "pm_name": {"mode": "header", "sheet": "Version Control", "column": "Prepapred by", "header_row": 2, "row": -1},
    "gm_name": {"mode": "header", "sheet": "Version Control", "column": "Approved by", "header_row": 2, "row": -1},
    "pl_name": {"mode": "header", "sheet": "Version Control", "column": "PL Name", "header_row": 2, "row": -1},
    "branch_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Branch.1", "header_row": 31, "row": -1},
    "inhouse_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Inhouse.1", "header_row": 31, "row": -1},
    "throughput_branch": {"mode": "header", "sheet": "Project Insights", "column": "Branch", "header_row": 31, "row": -1},
    "throughput_inhouse": {"mode": "header", "sheet": "Project Insights", "column": "Inhouse", "header_row": 31, "row": -1},
    "quoted_throughput": {"mode": "cell", "sheet": "Project Insights", "cell": "B17"},
    "weekly_delivery_rows": {"sheet": "Weekly Delivery Plan"},
    "daily_metrics": {
      "branch_receipt": {"sheet": "Inventory", "date_column": "P", "value_column": "R"},
      "rqc_completed": {"sheet": "Inventory", "date_column": "AK", "value_column": "R"},
      "rqc_quality_score": {"sheet": "Inventory", "value_column": "AL", "agg": "avg"}
    }
}

smc_config = {
    "project_name": {"mode": "cell", "sheet": "Version Control", "cell": "B1"},
    "branch": {"mode": "static", "value": "TDM"},
    "start_date": {"mode": "cell", "sheet": "Project Summary", "cell": "D1"},
    "end_date": {"mode": "cell", "sheet": "Project Summary", "cell": "F1"},
    "target": {"mode": "cell", "sheet": "Project Summary", "cell": "B2"},
    "delivered": {"mode": "cell", "sheet": "Project Summary", "cell": "B4"},
    "images": {"mode": "sum_column", "sheet": "Calculation", "column": "Total Image"},
    "event_type": {"mode": "cell", "sheet": "Project Insights", "cell": "A3"},
    "extra_fields": {
      "Volume Unit": {"mode": "cell", "sheet": "Project Summary", "cell": "C2"},
      "Days Gone": {"mode": "cell", "sheet": "Project Summary", "cell": "C4"},
      "Delivered % (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B5"},
      "Days Gone %": {"mode": "cell", "sheet": "Project Summary", "cell": "B6"},
      "Remaining Records (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B8"},
      "Remaining Days (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "C8"},
      "Total Duration (Days)": {"mode": "cell", "sheet": "Project Summary", "cell": "H1"}
    },
    "inventory_rows": {
      "sheet": "Calculation",
      "columns": {
        "file_name": "DGS No",
        "event_type": "Event Type",
        "image_count": "Total Image",
        "record_count": "Total Record",
        "shipment_date": "Export_Date"
      }
    },
    "pm_name": {"mode": "header", "sheet": "Version Control", "column": "Prepapred by", "header_row": 2, "row": -1},
    "gm_name": {"mode": "header", "sheet": "Version Control", "column": "Approved by", "header_row": 2, "row": -1},
    "pl_name": {"mode": "header", "sheet": "Version Control", "column": "PL Name", "header_row": 2, "row": -1},
    "branch_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Branch.1", "header_row": 22, "row": -1},
    "inhouse_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Inhouse.1", "header_row": 22, "row": -1},
    "throughput_branch": {"mode": "header", "sheet": "Project Insights", "column": "Branch", "header_row": 22, "row": -1},
    "throughput_inhouse": {"mode": "header", "sheet": "Project Insights", "column": "Inhouse", "header_row": 22, "row": -1},
    "quoted_throughput": {"mode": "cell", "sheet": "Project Insights", "cell": "B16"},
    "weekly_delivery_rows": {"sheet": "Weekly Delivery Plan"},
    "daily_metrics": {
      "branch_receipt": {"sheet": "Inventory_Index", "date_column": "R", "value_column": "S"},
      "rqc_completed": {"sheet": "Inventory_Index", "date_column": "AG", "value_column": "S"},
      "rqc_quality_score": {"sheet": "Inventory_Index", "value_column": "AH", "agg": "avg"}
    }
}

fiji_config = {
    "project_name": {"mode": "cell", "sheet": "Version Control", "cell": "B1"},
    "branch": {"mode": "static", "value": "TDM"},
    "start_date": {"mode": "cell", "sheet": "Project Summary", "cell": "D1"},
    "end_date": {"mode": "cell", "sheet": "Project Summary", "cell": "F1"},
    "target": {"mode": "cell", "sheet": "Project Summary", "cell": "B2"},
    "delivered": {"mode": "cell", "sheet": "Project Summary", "cell": "B4"},
    "images": {"mode": "sum_column", "sheet": "Inventory", "column": "# of Images"},
    "language": {"mode": "cell", "sheet": "Inventory", "cell": "H2"},
    "event_type": {"mode": "cell", "sheet": "Project Insights", "cell": "A3"},
    "extra_fields": {
      "Volume Unit": {"mode": "cell", "sheet": "Project Summary", "cell": "C2"},
      "Days Gone": {"mode": "cell", "sheet": "Project Summary", "cell": "C4"},
      "Delivered % (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B5"},
      "Days Gone %": {"mode": "cell", "sheet": "Project Summary", "cell": "B6"},
      "Remaining Records (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B8"},
      "Remaining Days (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "C8"},
      "Total Duration (Days)": {"mode": "cell", "sheet": "Project Summary", "cell": "H1"}
    },
    "inventory_rows": {
      "sheet": "Inventory",
      "columns": {
        "folder_name": "Folder",
        "file_name": "DGS No",
        "language": "Language",
        "image_count": "# of Images",
        "record_count": "Accepted Records",
        "shipment_date": "Shipment Date"
      }
    },
    "pm_name": {"mode": "header", "sheet": "Version Control", "column": "Prepapred by", "header_row": 2, "row": -1},
    "gm_name": {"mode": "header", "sheet": "Version Control", "column": "Approved by", "header_row": 2, "row": -1},
    "pl_name": {"mode": "header", "sheet": "Version Control", "column": "PL Name", "header_row": 2, "row": -1},
    "branch_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Manpower Used", "header_row": 12, "row": -1},
    "throughput_branch": {"mode": "header", "sheet": "Project Insights", "column": "Throughtput", "header_row": 12, "row": -1},
    "quoted_throughput": {"mode": "cell", "sheet": "Project Insights", "cell": "B11"},
    "weekly_delivery_rows": {"sheet": "Weekly Delivery Plan"},
    "daily_metrics": {
      "branch_receipt": {"sheet": "Inventory", "date_column": "P", "value_column": "Q"},
      "rqc_completed": {"sheet": "Inventory", "date_column": "AG", "value_column": "Q"},
      "rqc_quality_score": {"sheet": "Inventory", "value_column": "AD", "agg": "avg"}
    }
}

newspaper_config = {
    "project_name": {"mode": "cell", "sheet": "Version Control", "cell": "B1"},
    "branch": {"mode": "static", "value": "TDM"},
    "start_date": {"mode": "cell", "sheet": "Project Summary", "cell": "D1"},
    "end_date": {"mode": "cell", "sheet": "Project Summary", "cell": "F1"},
    "target": {"mode": "cell", "sheet": "Project Summary", "cell": "B2"},
    "delivered": {"mode": "cell", "sheet": "Project Summary", "cell": "B4"},
    "images": {"mode": "sum_column", "sheet": "Inventory", "column": "# Images"},
    "event_type": {"mode": "cell", "sheet": "Project Insights", "cell": "A3"},
    "extra_fields": {
      "Volume Unit": {"mode": "cell", "sheet": "Project Summary", "cell": "C2"},
      "Days Gone": {"mode": "cell", "sheet": "Project Summary", "cell": "C4"},
      "Delivered % (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B5"},
      "Days Gone %": {"mode": "cell", "sheet": "Project Summary", "cell": "B6"},
      "Remaining Records (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "B8"},
      "Remaining Days (as reported)": {"mode": "cell", "sheet": "Project Summary", "cell": "C8"},
      "Total Duration (Days)": {"mode": "cell", "sheet": "Project Summary", "cell": "H1"}
    },
    "inventory_rows": {
      "sheet": "Inventory",
      "columns": {
        "folder_name": "Folder Name",
        "file_name": "File Name",
        "image_count": "# Images",
        "record_count": "Accepted Images",
        "shipment_date": "Shipment"
      }
    },
    "pm_name": {"mode": "header", "sheet": "Version Control", "column": "Prepapred by", "header_row": 2, "row": -1},
    "gm_name": {"mode": "header", "sheet": "Version Control", "column": "Approved by", "header_row": 2, "row": -1},
    "pl_name": {"mode": "header", "sheet": "Version Control", "column": "PL Name", "header_row": 2, "row": -1},
    "branch_manpower_count": {"mode": "header", "sheet": "Project Insights", "column": "Head Count", "header_row": 17, "row": -1},
    "throughput_branch": {"mode": "header", "sheet": "Project Insights", "column": "Throughput", "header_row": 17, "row": -1},
    "quoted_throughput": {"mode": "cell", "sheet": "Project Insights", "cell": "B18"},
    "weekly_delivery_rows": {"sheet": "Weekly Delivery Plan"},
    "daily_metrics": {
      "branch_receipt": {"sheet": "Inventory", "date_column": "B", "value_column": "E"},
      "rqc_completed": {"sheet": "Inventory", "date_column": "L", "value_column": "M"},
      "rqc_quality_score": {"sheet": "Inventory", "value_column": "AA", "agg": "avg"}
    }
}

tests = [
    ("LATVIA", r"media\uploads\gsheet_1XMcjg0x_dac56f.xlsx", latvia_config),
    ("SMC", r"media\uploads\gsheet_1kvJJYAK_f76fc1.xlsx", smc_config),
    ("FIJI", r"media\uploads\gsheet_1KY0YBnI_c178db.xlsx", fiji_config),
    ("NEWSPAPER", r"media\uploads\gsheet_1FniG5GO_5e8fec.xlsx", newspaper_config),
]

for key, path, cfg in tests:
    print("=" * 60)
    print(f"Testing {key} on {path}...")
    res = apply_mapping(path, cfg)
    print(f"  Valid: {res.is_valid}")
    print(f"  Errors: {res.errors}")
    print(f"  Warnings: {res.warnings}")
    print(f"  Values: {res.values}")
    print(f"  Extra: {res.extra}")
    print(f"  Inventory Rows: {len(res.inventory_rows)}")
    print(f"  Weekly Delivery Rows: {len(res.weekly_delivery_rows)}")
    print(f"  Daily Metrics: {res.daily_metrics}")
