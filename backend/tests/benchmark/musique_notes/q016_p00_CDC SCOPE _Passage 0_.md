# CDC SCOPE (Passage 0)

Passage 1:
CDC SCOPE
SCOPE (Supervisory Control of Program Execution) is a series of Control Data Corporation batch operating systems developed in the 1960s.

Variants
SCOPE for the CDC 3000 series
SCOPE for the CDC 6000 series
SCOPE and SCOPE-2 for the CDC 7600/Cyber-76

SCOPE for the CDC 3000 series
SCOPE for the CDC 6000 series
This operating system was based on the original Chippewa Operating System. In the early 1970s, it was renamed NOS/BE for the CDC Cyber machines. The SCOPE operating system is a file-oriented system using mass storage, random access devices. It was designed to make use of all capabilities of CDC 6000 computer systems and exploits fully the multiple-operating modes of all segments of the computer. Main tasks of SCOPE are controlling job execution, storage assignment, performing segment and overlay loading. Its features include comprehensive input/output functions and library maintenance routines. The operating system chronologically records all jobs run and any problems encountered. To aid debugging, dumps and memory maps are available.

Description
SCOPE is a multiprogramming operating system capable of running up to eight jobs, called control points, at one time. One control point is used for system functions.: p.1-2  Later versions increased this limit to 15.
SCOPE runs on the 6x00's peripheral processors (PPs). "A central processor (CP)… is completely within the power of every PP at all times." One PP, identified as PP0 runs the Monitor Program (MTR) "that oversees or controls all other activities." PP9 is assigned to control the system console typewriter and displays. The other PPs perform input/output functions as directed by MTR.: p.1-1 A portion of the central processor's memory (called central memory, or CM) the Central Memory Resident (CMR) "is reserved for various system tables accessible by the PPs.”: p.1-2  Part of this CMR is a communications area for each PP. Each communications area contains an "input register" and an "output register", followed by a message buffer.: p.1-1 When the computer is deadstarted, all PP's are loaded with system code from magnetic tape. PP0 will begin running the monitor code. The remaining PPs will loop reading their input registers waiting for requests from the monitor.: p.1-1

Software
As of SCOPE 3.3 a number of programming language compilers and utilities were supported. Major languages were ALGOL, BASIC, FORTRAN, COBOL, and COMPASS (assembler). Other languages were APT, CSSL 3 (Continuous System Simulation Language), JOVIAL, SIMSCRIPT, and SIMULA. Other software included IGS (Interactive Graphics System), PERT, and SORT/MERGE.CDC systems were considered supercomputers, and customers were often large government agencies and research facilities. Most of these had specialized requirements, and often wrote their own software.

Competition
SCOPE was written by a programming team in Sunnyvale, California, about 2,000 miles from the CDC hardware division.  It was considered by them a buggy and inefficient piece of software, though not much different than many operating systems of the era.  At the CDC Arden Hills, Minnesota laboratories (where they referred to SCOPE as Sunnyvale's Collection Of Programming Errors) they had a competing operating system, MACE.  This was the Mansfield And Cahlander Executive (from Greg Mansfield and Dave Cahlander, the authors of the system).  It had started as an engineering test executive, but eventually developed into a complete operating system — a modularized rewrite and enhancement of the original Chippewa Operating System (COS).  While never an official CDC product, a copy was freely given to any customer who asked for one.  Many customers did, especially the more advanced ones (like University and research sites).
When Control Data decided to write its next operating system Kronos, it considered both the current SCOPE system and the unofficial MACE alternative.  They chose to abandon the SCOPE system and base Kronos on the MACE software.  Eventually, Kronos was replaced by the new Network Operating System (NOS).  Though many smaller CDC customers continued to use the SCOPE system rather than Kronos.  When NOS became the primary Control Data operating system, some customers running mainly batch operations were reluctant to switch to the NOS system, as they saw no benefit for their shop.  So the SCOPE system was maintained, and renamed as NOS/BE (Batch Environment), primarily so that CDC Marketing could say that all mainframe customers were using the NOS operating system.

Current status
The computer emulation community has made repeated attempts to recover and preserve CDC software. It is now running under a CDC CYBER and 6000 series emulator.

See also
CDC Kronos
NOS
