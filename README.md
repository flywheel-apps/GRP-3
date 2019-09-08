# GRP-3
Metadata Import and Validation: DICOM

# Implementation

Adapt DICOM classification gear to validate dicom file header, check against a template, report issues, convert to JSON, and attach to the appropriate metadata container in Flywheel:  file, subject, session etc in Flywheel database - _this will be determined by the parent container_. 

The Goal here is to provide an example gear that reads DICOM headers, validates that against a template 

### Inputs
##### 1. DICOM archive
* Assume '.dicom.zip'

##### 2. Template/Project context
(OPEN QUESTION: What format will this be in and where will it be stored)
I would lobby for this template to be stored as metadata on the project (provided to the gear as context input)
Let's support both project context and json input file (stored on the project). i.e., look for the info, and file on the project (trial)


### Workflow
The user uploads some DICOM data. I envision this gear running as a rule when a DICOM file comes in
1. Read in the DCIOM header data - convert to json
2. Read in the template from project context or _trial.template.json_ attached to the project
3. Validate DICOM header metadata against the template (support regex)
4. For DICOM files in acquisition, check for inconsistent intervals between slices
5. Generate error if fields are missing or invalid
6. If validation errors are found:
*  tag the container
*  log the error 
* optionally write out error file - see below.


### Outputs
1. `.metadata.json` file containing the valid metadata that will by placed in FW, on the specified container.
2. `.metadata error` log (csv file with the fieldname, value (if applicable), and error (e.g., missing vs invalid)


### Other considerations
* Acquisition tags are not visible in the UI presently.
* This funcitonality could be added to [GRP-1|https://flywheelio.atlassian.net/jira/software/projects/GRP/boards/27?selectedIssue=GRP-1]

