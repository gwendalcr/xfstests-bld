"""The gen_results_summary module generates a summary report given a
results directory.

The summary report is primarily generated using the results.xml files
in the results directory.  If there is a ltm-run-stats file in the
top-level directory, then assume that the results directory was
generated by the LTM server.  In LTM mode we sort the test suite
reports by the order the LTM server launched the VM's.

In the future, if we start using multiple VM's to run tests for a
specific file system config, we'll need to make this module smarter.

"""
import copy
import os
import sys
import time
from datetime import datetime
from junitparser import JUnitXml, Property, Properties, Failure, Error, Skipped

def get_results(dirroot):
    """Return a list of files named results.xml in a directory hierarchy"""
    for dirpath, _dirs, filenames in os.walk(dirroot):
        if 'results.xml' in filenames:
            yield dirpath + '/results.xml'

def parse_timestamp(timestamp):
    """Parse an ISO-8601-like timestamp as found in an xUnit file."""
    return time.mktime(datetime.strptime(timestamp,
                                         '%Y-%m-%dT%H:%M:%S').timetuple())

def failed_tests(testsuite):
    """This iterator the failed tests from the testsuite."""
    for testcase in testsuite:
        if isinstance(testcase.result, Failure):
            yield testcase

def get_property(props, key):
    """Return the value of the first property with the given name"""
    if props is None:
        return None
    for prop in props:
        if prop.name == key:
            return prop.value
    return None

def get_properties(props, key):
    """An interator which returns values of properties with a given name."""
    if props is None:
        yield None
    for prop in props:
        if prop.name == key:
            yield prop.value

def remove_properties(props, key):
    """Remove properties with a given name."""
    if props is None:
        return
    for prop in props:
        if prop.name == key:
            props.remove(prop)

def print_tests(out_f, testsuite, result_type, type_label):
    """Print all of the tests which match a particular result_type"""
    found = False
    pos = 0
    for testcase in testsuite:
        if not isinstance(testcase.result, result_type):
            continue
        if not found:
            out_f.write('  %s: ' % type_label)
            pos = len(type_label) + 4
            found = True
        name_len = len(testcase.name) + 1
        pos += name_len + 1
        if pos > 76:
            out_f.write('\n    ')
            pos = name_len + 5
        out_f.write(testcase.name + ' ')
    if found:
        out_f.write('\n')

def total_tests(testsuites):
    """Print the total number of tests in an array of testsuites"""
    total = 0
    for testsuite in testsuites:
        if testsuite.tests is not None:
            total += testsuite.tests
    return total

def sum_testsuites(testsuites):
    """Summarize all of the test suite statistics"""
    runtime = 0
    tests = 0
    skipped = 0
    failures = 0
    errors = 0
    for testsuite in testsuites:
        runtime += testsuite.time
        tests += testsuite.tests
        skipped += testsuite.skipped
        failures += testsuite.failures
        errors += testsuite.errors
    return (tests, skipped, failures, errors, runtime)

def print_summary(out_f, testsuite, verbose):
    """Print a summary for a particular test suite

    Print the file system configuration, the number of tests run,
    skipped, and failed.  If there are any failed tests, print a list
    of the failed tests.  The output will look something like this:

    ext4/bigalloc 244 tests, 25 skipped, 5 errors, 880 seconds
       generic/219 generic/235 generic/422 generic/451 generic/456
    """
    cfg = get_property(testsuite.properties(), 'TESTCFG')
    if cfg is None:
        cfg = get_property(testsuite.properties(), 'FSTESTCFG')

    runtime = testsuite.time
    tests = testsuite.tests
    skipped = testsuite.skipped
    failures = testsuite.failures
    errors = testsuite.errors
    out_f.write('%s: %d tests, ' % (cfg, tests))
    if failures > 0:
        out_f.write('%d failures, ' % failures)
    if errors > 0:
        out_f.write('%d errors, ' % errors)
    if skipped > 0:
        out_f.write('%d skipped, ' % skipped)
    out_f.write('%d seconds\n' % runtime)
    if verbose:
        for test_case in testsuite:
            status = 'Pass'
            if isinstance(test_case.result, Failure):
                status = 'Failed'
            if isinstance(test_case.result, Skipped):
                status = 'Skipped'
            if isinstance(test_case.result, Error):
                status = 'Error'
            out_f.write("  %-12s %-8s %ds\n" %
                        (test_case.name, status, test_case.time))
    else:
        if failures > 0:
            print_tests(out_f, testsuite, Failure, 'Failures')
            if errors > 0:
                print_tests(out_f, testsuite, Error, 'Errors')

def print_property_line(out_f, props, key):
    """Print a line containing the given property."""
    value = get_property(props, key)
    if value is not None and value != "":
        out_f.write('%-10s %s\n' % (key + ':', value))

def print_properties(out_f, props, key):
    """Print multiple property lines."""
    for value in get_properties(props, key):
        out_f.write('%-10s %s\n' % (key + ':', value))

def print_header(out_f, props):
    """Print the header of the report."""
    print_property_line(out_f, props, 'TESTRUNID')
    print_property_line(out_f, props, 'KERNEL')
    print_property_line(out_f, props, 'CMDLINE')
    print_property_line(out_f, props, 'CPUS')
    print_property_line(out_f, props, 'MEM')
    print_property_line(out_f, props, 'MNTOPTS')
    out_f.write('\n')

def print_trailer(out_f, props):
    """Print the trailer of the report."""
    out_f.write('\n')
    print_property_line(out_f, props, 'FSTESTIMG')
    print_property_line(out_f, props, 'FSTESTPRJ')
    print_properties(out_f, props, 'FSTESTVER')
    print_property_line(out_f, props, 'FSTESTCFG')
    print_property_line(out_f, props, 'FSTESTSET')
    print_property_line(out_f, props, 'FSTESTEXC')
    print_property_line(out_f, props, 'FSTESTOPT')
    print_property_line(out_f, props, 'GCE ID')

def check_for_ltm(results_dir, props):
    """Check to see if the results directory was created by the LTM and
    adjust the properties accordingly.  Returns true if we are in LTM
    mode.
    """
    try:
        out_f = open(os.path.join(results_dir, 'ltm-run-stats'))
        for line in out_f:
            key, value = line.split(': ', 1)
            value = value.rstrip('\n').strip('"')
            remove_properties(props, key)
            props.add_property(Property(key, value))
        out_f.close()
        remove_properties(props, 'GCE ID')
        remove_properties(props, 'FSTESTCFG')
        return True
    except IOError:
        sys.exc_clear()
        return False

def gen_results_summary(results_dir, output_fn=None, merge_fn=None,
                        verbose=False):
    """Scan a results directory and generate a summary file"""
    reports = []
    combined = JUnitXml()
    nr_files = 0
    out_f = sys.stdout

    for filename in get_results(results_dir):
        reports.append(JUnitXml.fromfile(filename))

    if len(reports) == 0:
        return 0

    if output_fn is not None:
        out_f = open(output_fn, "w")

    props = copy.deepcopy(reports[0].child(Properties))

    ltm = check_for_ltm(results_dir, props)

    print_header(out_f, props)

    sort_by = lambda ts: parse_timestamp(ts.timestamp)
    if ltm:
        sort_by = lambda ts: ts.hostname

    if total_tests(reports) < 30:
        verbose = True

    for testsuite in sorted(reports, key=sort_by):
        print_summary(out_f, testsuite, verbose)
        combined.add_testsuite(testsuite)
        nr_files += 1

    out_f.write('Totals: %d tests, %d skipped, %d failures, %d errors, %ds\n' \
                % sum_testsuites(reports))

    print_trailer(out_f, props)

    if merge_fn is not None:
        combined.update_statistics()
        combined.write(merge_fn + '.new')
        if os.path.exists(merge_fn):
            os.rename(merge_fn, merge_fn + '.bak')
        os.rename(merge_fn + '.new', merge_fn)

    return nr_files
