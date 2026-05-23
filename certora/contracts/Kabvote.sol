// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract KabVote {

    uint256 public constant MIN_STUDENT_ID = 202000000;
    uint256 public constant MAX_STUDENT_ID = 202699999;
    uint256 public constant CANDIDATE_REGISTRATION_FEE = 0.05 ether;

    enum ElectionState { NOT_STARTED, REGISTRATION_OPEN, VOTING_ACTIVE, VOTING_ENDED, RESULTS_PUBLISHED, CANCELLED }
    enum VoterStatus { NOT_REGISTERED, PENDING_VERIFICATION, VERIFIED, REJECTED, SUSPENDED }
    enum ProgramLevel { CERTIFICATE, DIPLOMA, BACHELOR, MASTERS, PHD }
    enum Faculty { NONE, AGRICULTURE_AND_ENVIRONMENTAL_SCIENCES, ARTS_AND_SOCIAL_SCIENCES, COMPUTING_LIBRARY_AND_INFO_SCIENCE, EDUCATION, ENGINEERING_TECHNOLOGY_APPLIED_DESIGN_ART, LAW, SCIENCE, ECONOMICS_AND_MANAGEMENT_SCIENCES, SCHOOL_OF_MEDICINE, INSTITUTE_OF_LANGUAGES, INSTITUTE_OF_TOURISM_AND_HOSPITALITY }

    struct Student {
        uint256 studentId;
        string fullName;
        Faculty faculty;
        ProgramLevel programLevel;
        uint256 admissionYear;
        uint256 expectedGraduationYear;
        uint256 voteWeight;
        bool isActive;
        VoterStatus status;
        uint256 registeredAt;
        bytes32 studentHash;
        uint256 academicYear;
    }

    struct Candidate {
        uint256 id;
        string name;
        Faculty faculty;
        string position;
        string manifestoHash;
        uint256 voteCount;
        uint256 voteWeightedCount;
        bool exists;
        bool isApproved;
        uint256 registrationFee;
    }

    struct ElectionRound {
        uint256 roundId;
        string title;
        string description;
        uint256 registrationStart;
        uint256 registrationEnd;
        uint256 votingStart;
        uint256 votingEnd;
        uint256 totalVotesCast;
        uint256 totalWeightedVotes;
        bool isActive;
    }

    address public immutable admin;
    ElectionState public currentState;
    uint256 public currentRoundId;
    mapping(uint256 => ElectionRound) public electionRounds;
    mapping(address => Student) public students;
    uint256 public totalVerifiedVoters;
    mapping(Faculty => uint256) public facultyVoterCount;
    mapping(uint256 => Candidate) public candidates;
    uint256 public totalCandidates;
    mapping(Faculty => uint256[]) public facultyCandidates;
    mapping(uint256 => mapping(address => bool)) public hasVotedInRound;
    mapping(uint256 => mapping(uint256 => uint256)) public roundCandidateVotes;
    bool public emergencyPaused;

    mapping(Faculty => uint256) public bachelorDuration;
    mapping(Faculty => uint256) public diplomaDuration;
    uint256 public constant HEC_DURATION = 1;

    event StudentRegistered(address indexed voter, uint256 indexed studentId, string fullName, Faculty faculty, ProgramLevel level, uint256 voteWeight);
    event CandidateRegistered(uint256 indexed candidateId, string name, Faculty faculty, string position);
    event VoteCast(address indexed voter, uint256 indexed roundId, uint256 indexed candidateId, uint256 weight);
    event ElectionRoundStarted(uint256 indexed roundId, uint256 votingStart, uint256 votingEnd);
    event ElectionRoundEnded(uint256 indexed roundId, uint256 totalVotes, uint256 totalWeightedVotes);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin");
        _;
    }

    modifier notPaused() {
        require(!emergencyPaused, "Emergency paused");
        _;
    }

    modifier validStudentId(uint256 _studentId) {
        require(_studentId >= MIN_STUDENT_ID && _studentId <= MAX_STUDENT_ID, "Invalid student ID");
        _;
    }

    modifier studentExists(address _voter) {
        require(students[_voter].isActive, "Student not registered");
        require(students[_voter].status == VoterStatus.VERIFIED, "Student not verified");
        _;
    }

    modifier electionInState(ElectionState _state) {
        require(currentState == _state, "Wrong election state");
        _;
    }

    modifier validCandidate(uint256 _candidateId) {
        require(candidates[_candidateId].exists, "Candidate not found");
        require(candidates[_candidateId].isApproved, "Candidate not approved");
        _;
    }

    modifier votingPeriodActive() {
        ElectionRound memory round = electionRounds[currentRoundId];
        require(block.timestamp >= round.votingStart, "Voting not started");
        require(block.timestamp <= round.votingEnd, "Voting ended");
        _;
    }

    constructor() {
        admin = msg.sender;
        currentState = ElectionState.NOT_STARTED;
        currentRoundId = 1;
        emergencyPaused = false;

        bachelorDuration[Faculty.SCHOOL_OF_MEDICINE] = 5;
        bachelorDuration[Faculty.LAW] = 4;
        bachelorDuration[Faculty.ENGINEERING_TECHNOLOGY_APPLIED_DESIGN_ART] = 4;
        bachelorDuration[Faculty.AGRICULTURE_AND_ENVIRONMENTAL_SCIENCES] = 3;
        bachelorDuration[Faculty.ARTS_AND_SOCIAL_SCIENCES] = 3;
        bachelorDuration[Faculty.COMPUTING_LIBRARY_AND_INFO_SCIENCE] = 3;
        bachelorDuration[Faculty.EDUCATION] = 3;
        bachelorDuration[Faculty.SCIENCE] = 3;
        bachelorDuration[Faculty.ECONOMICS_AND_MANAGEMENT_SCIENCES] = 3;
        bachelorDuration[Faculty.INSTITUTE_OF_LANGUAGES] = 3;
        bachelorDuration[Faculty.INSTITUTE_OF_TOURISM_AND_HOSPITALITY] = 3;

        diplomaDuration[Faculty.SCHOOL_OF_MEDICINE] = 3;
        diplomaDuration[Faculty.ENGINEERING_TECHNOLOGY_APPLIED_DESIGN_ART] = 3;
        diplomaDuration[Faculty.AGRICULTURE_AND_ENVIRONMENTAL_SCIENCES] = 2;
        diplomaDuration[Faculty.ARTS_AND_SOCIAL_SCIENCES] = 2;
        diplomaDuration[Faculty.COMPUTING_LIBRARY_AND_INFO_SCIENCE] = 2;
        diplomaDuration[Faculty.EDUCATION] = 2;
        diplomaDuration[Faculty.LAW] = 2;
        diplomaDuration[Faculty.SCIENCE] = 2;
        diplomaDuration[Faculty.ECONOMICS_AND_MANAGEMENT_SCIENCES] = 2;
        diplomaDuration[Faculty.INSTITUTE_OF_LANGUAGES] = 2;
        diplomaDuration[Faculty.INSTITUTE_OF_TOURISM_AND_HOSPITALITY] = 2;
    }

    function calculateVoteWeight(Faculty _faculty, ProgramLevel _level, uint256 _admissionYear) public view returns (uint256) {
        uint256 currentYear = 2026;
        uint256 yearsStudied = currentYear - _admissionYear;
        uint256 totalDuration;
        
        if (_level == ProgramLevel.CERTIFICATE) totalDuration = HEC_DURATION;
        else if (_level == ProgramLevel.DIPLOMA) totalDuration = diplomaDuration[_faculty];
        else if (_level == ProgramLevel.BACHELOR) totalDuration = bachelorDuration[_faculty];
        else totalDuration = 1;
        
        if (yearsStudied > totalDuration) yearsStudied = totalDuration;
        uint256 weight = yearsStudied + 1;
        if (weight > 5) weight = 5;
        if (weight < 1) weight = 1;
        return weight;
    }

    function registerStudent(uint256 _studentId, string calldata _fullName, Faculty _faculty, ProgramLevel _programLevel, uint256 _admissionYear, bytes32 _studentHash) external validStudentId(_studentId) electionInState(ElectionState.REGISTRATION_OPEN) notPaused {
        require(!students[msg.sender].isActive, "Already registered");
        require(_faculty != Faculty.NONE, "Invalid faculty");
        require(_admissionYear >= 2020 && _admissionYear <= 2026, "Invalid admission year");
        
        uint256 voteWeight = calculateVoteWeight(_faculty, _programLevel, _admissionYear);
        uint256 expectedGraduation = _admissionYear;
        if (_programLevel == ProgramLevel.BACHELOR) expectedGraduation += bachelorDuration[_faculty];
        else if (_programLevel == ProgramLevel.DIPLOMA) expectedGraduation += diplomaDuration[_faculty];
        else if (_programLevel == ProgramLevel.CERTIFICATE) expectedGraduation += HEC_DURATION;
        
        students[msg.sender] = Student(_studentId, _fullName, _faculty, _programLevel, _admissionYear, expectedGraduation, voteWeight, true, VoterStatus.PENDING_VERIFICATION, block.timestamp, _studentHash, 1);
        facultyVoterCount[_faculty]++;
        
        emit StudentRegistered(msg.sender, _studentId, _fullName, _faculty, _programLevel, voteWeight);
    }

    function verifyStudent(address _student) external onlyAdmin {
        require(students[_student].isActive, "Student not found");
        require(students[_student].status == VoterStatus.PENDING_VERIFICATION, "Wrong status");
        students[_student].status = VoterStatus.VERIFIED;
        totalVerifiedVoters++;
    }

    function registerCandidate(string calldata _name, Faculty _faculty, string calldata _position, string calldata _manifestoHash) external payable electionInState(ElectionState.REGISTRATION_OPEN) notPaused {
        require(bytes(_name).length > 0, "Name required");
        require(_faculty != Faculty.NONE, "Faculty required");
        require(msg.value >= CANDIDATE_REGISTRATION_FEE, "Fee required");
        
        totalCandidates++;
        candidates[totalCandidates] = Candidate(totalCandidates, _name, _faculty, _position, _manifestoHash, 0, 0, true, false, msg.value);
        facultyCandidates[_faculty].push(totalCandidates);
        emit CandidateRegistered(totalCandidates, _name, _faculty, _position);
    }

    function approveCandidate(uint256 _candidateId) external onlyAdmin {
        require(candidates[_candidateId].exists, "Candidate not found");
        require(!candidates[_candidateId].isApproved, "Already approved");
        candidates[_candidateId].isApproved = true;
    }

    function vote(uint256 _candidateId) external studentExists(msg.sender) votingPeriodActive validCandidate(_candidateId) notPaused {
        require(!hasVotedInRound[currentRoundId][msg.sender], "Already voted");
        Student memory student = students[msg.sender];
        candidates[_candidateId].voteCount++;
        candidates[_candidateId].voteWeightedCount += student.voteWeight;
        electionRounds[currentRoundId].totalVotesCast++;
        electionRounds[currentRoundId].totalWeightedVotes += student.voteWeight;
        hasVotedInRound[currentRoundId][msg.sender] = true;
        roundCandidateVotes[currentRoundId][_candidateId]++;
        emit VoteCast(msg.sender, currentRoundId, _candidateId, student.voteWeight);
    }

    function createElectionRound(string calldata _title, string calldata _description, uint256 _registrationStart, uint256 _registrationEnd, uint256 _votingStart, uint256 _votingEnd) external onlyAdmin {
        require(_votingStart > _registrationEnd, "Invalid timeline");
        require(_votingEnd > _votingStart, "Invalid voting period");
        currentRoundId++;
        electionRounds[currentRoundId] = ElectionRound(currentRoundId, _title, _description, _registrationStart, _registrationEnd, _votingStart, _votingEnd, 0, 0, true);
        currentState = ElectionState.REGISTRATION_OPEN;
        emit ElectionRoundStarted(currentRoundId, _votingStart, _votingEnd);
    }

    function startVoting() external onlyAdmin {
        require(currentState == ElectionState.REGISTRATION_OPEN, "Wrong state");
        require(block.timestamp >= electionRounds[currentRoundId].votingStart, "Voting not ready");
        currentState = ElectionState.VOTING_ACTIVE;
    }

    function endVoting() external onlyAdmin {
        require(currentState == ElectionState.VOTING_ACTIVE, "Wrong state");
        currentState = ElectionState.VOTING_ENDED;
        emit ElectionRoundEnded(currentRoundId, electionRounds[currentRoundId].totalVotesCast, electionRounds[currentRoundId].totalWeightedVotes);
    }

    function pauseEmergency() external onlyAdmin { emergencyPaused = true; }
    function unpauseEmergency() external onlyAdmin { emergencyPaused = false; }

    function getStudentInfo(address _voter) external view returns (uint256 studentId, string memory fullName, Faculty faculty, ProgramLevel programLevel, uint256 voteWeight, uint256 academicYear, VoterStatus status) {
        Student memory student = students[_voter];
        return (student.studentId, student.fullName, student.faculty, student.programLevel, student.voteWeight, student.academicYear, student.status);
    }

    function getCandidateInfo(uint256 _candidateId) external view returns (string memory name, Faculty faculty, string memory position, uint256 voteCount, uint256 voteWeightedCount, bool isApproved) {
        Candidate memory candidate = candidates[_candidateId];
        return (candidate.name, candidate.faculty, candidate.position, candidate.voteCount, candidate.voteWeightedCount, candidate.isApproved);
    }

    function getCurrentRoundInfo() external view returns (uint256 roundId, string memory title, uint256 votingStart, uint256 votingEnd, ElectionState state) {
        ElectionRound memory round = electionRounds[currentRoundId];
        return (currentRoundId, round.title, round.votingStart, round.votingEnd, currentState);
    }

    function getFacultyVoterCount(Faculty _faculty) external view returns (uint256) {
        return facultyVoterCount[_faculty];
    }

    function hasVoted(address _voter, uint256 _roundId) external view returns (bool) {
        return hasVotedInRound[_roundId][_voter];
    }
}
