[![CircleCI](https://circleci.com/gh/flywheel-apps/GRP-3.svg?style=svg)](https://circleci.com/gh/flywheel-apps/GRP-3)

# flywheel/GRP-3
Metadata Import and Validation: DICOM

GRP-3 is a Flywheel gear for importing and validating DICOM header data. It is a variant of [scitran-apps/dicom-mr-classifier](https://github.com/scitran-apps/dicom-mr-classifier/). 

## Inputs

### dicom (required)
dicom is the DICOM file from which to parse, validate, and import metadata into flywheel. 

### json_template (required)
The json_template is a [JSON Schema](https://json-schema.org/understanding-json-schema/) template that specifies validation rules for DICOM header values. It supports all Draft7Validator-compatible JSON Schema syntax.

### Manifest JSON for Inputs

```"inputs": {
    "dicom": {
      "base": "file",
      "description": "Dicom Archive",
      "optional": false,
      "type": {
        "enum": [
          "dicom"
        ]
      }
    },
    "json_template": {
      "base": "file",
      "description": "A JSON template to validate DICOM data",
      "optional": false,
      "type": {
        "enum": [
          "source code"
        ]
      }
    }
  }
```

## Configuration Options
GRP-3 does not have configuration options.

## Outputs
<DICOM file name>.error.log.json, a json file containing a list of dictionaries describing errors in validation. This file will only be written if validation errors are detected. 

### Flywheel metadata updates

* DICOM header fields will be added to the input DICOM file's file.info.header.dicom metadata in Flywheel
* `instrument` and `timestamp` will be set on the DICOM file's parent acquisition
* `operator`, `subject.age`, `subject.lastname`, `subject.sex`, `weight`, and `timestamp` will be set on the DICOM file's parent session
* If validation errors were detected, then the 'error' will be added to the acquisition's tags

## Troubleshooting
As with any gear, the Gear Logs are the first place to check when something appears to be amiss. Click the `Provenance` tab for the acquisition that contains the DICOM in question and click the `View Log` button to view the job log. 

If you require further assistance from Flywheel, please include a copy of the gear log, the input json_template and a link to the project/session/subject on which you ran the gear along with the acquisition label in your correspondence for best results.
