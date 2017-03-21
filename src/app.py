from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import datetime
import os

from config import DB_NAME, HOST, PORT, APP_SECRET_KEY

# Run Server
app = Flask(__name__)
app.secret_key = APP_SECRET_KEY


# MARK: DATABASE FUNCTIONS
def db_query(sql, data_list):
    """Returns none or a list of tuples from a SQL query and passed values."""
    conn = psycopg2.connect(dbname=DB_NAME, host=HOST, port=PORT)
    cur = conn.cursor()
    cur.execute(sql, data_list)

    # Return data as an array of dictionaries
    result = cur.fetchall()
    records = []

    # If the query returns something...
    if len(result) != 0:
        entries = result
        for row in entries:
            records.append(row)
    else:
        # No results in query
        return None

    conn.commit()
    cur.close()
    conn.close()
    return records


def db_change(sql, data_list):
    """Updates database using passed INSERT or UPDATE SQL command and vars."""
    conn = psycopg2.connect(dbname=DB_NAME, host=HOST, port=PORT)
    cur = conn.cursor()
    try:
        cur.execute(sql, data_list)
    except Exception as e:
        print("QUERY FAILED")
        print(e)
        redirect(url_for('failed_query'))

    conn.commit()
    cur.close()
    conn.close()


def duplicate_check(sql, data_list):
    """Returns True if a query yields a result and False if not."""
    conn = psycopg2.connect(dbname=DB_NAME, host=HOST, port=PORT)
    cur = conn.cursor()
    cur.execute(sql, data_list)
    result = cur.fetchall()
    cur.close()
    conn.close()
    if result:
        return True
    else:
        return False


def validate_date(date):
    """Confirms that user entered a date in the MM/DD/YYYY format."""
    try:
        date = datetime.datetime.strptime(date, '%m/%d/%Y').date()
        return date
    except ValueError:
        raise ValueError('Incorrect data format, should be MM/DD/YYYY')


# MARK: TEMPLATES
@app.route('/')
@app.route('/index')
@app.route('/index.html')
def index():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', None)
        password = request.form.get('password', None)

        if username is None:
            flash('Please enter a username.')
            return render_template('login.html')
        elif password is None:
            flash('Please enter a password.')
            return render_template('login.html')
        else:
            check_for_user = "SELECT * FROM users WHERE username = %s;"
            result = db_query(check_for_user, [username])

            # User DOES NOT exist:
            if result is None:
                flash('There is no record of this account.')
                return render_template('login.html')

            # User DOES exist:
            else:
                # Password is correct
                if password == result[0][3]:
                    session['username'] = username
                    session['logged_in'] = True
                    session['perms'] = result[0][1]
                    session['user_id'] = result[0][0]
                    return redirect('/dashboard')

                # Password is incorrect
                else:
                    flash('Password is incorrect.')
                    return render_template('login.html')

    return render_template('login.html')


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session['logged_in'] = False
    return render_template('logout.html')


@app.route('/create_user', methods=['GET', 'POST'])
def create_user():
    if request.method == 'POST':
        username = request.form.get('username', None).strip()
        password = request.form.get('password', None)
        role = request.form.get('role', 'Guest')

        if not username or not password or password == '':
            flash('Please enter a username and password.')
        else:
            # Form was completed
            matching_user = "SELECT user_pk FROM users WHERE username = %s;"
            user_does_exist = duplicate_check(matching_user, [username])

            if user_does_exist:
                flash('Username already exists')
            else:
                # User does not already exist - create it
                new_user = "INSERT INTO users (username, password, role_fk) VALUES (%s, %s, %s);"
                db_change(new_user, [username, password, role])
                flash('Your account was created!')

    return render_template('create_user.html')


@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('logged_in'):
        flash('You must login before being allowed access to the dashboard')
        return redirect(url_for('login'))

    cur_user = session['username']

    # POST METHOD
    if request.method == 'POST':
        # LOGISTICS OFFICER
        if session['perms'] == 2:
            selected_request = request.form.get('request_pk', None)
            load_date = request.form.get('load date', None)
            unload_date = request.form.get('unload date', None)

            # Form Completion Check
            if not selected_request:
                flash('Please choose a request to edit.')
                return redirect(url_for('dashboard'))
            elif selected_request == 'NO REQUESTS':
                flash('There are no requests to edit.')
                return redirect(url_for('dashboard'))
            elif not load_date and not unload_date:
                flash('Please at least fill in a load date.')
                return redirect(url_for('dashboard'))

            selected_request_query = ("SELECT "
                                      "r.request_pk, r.asset_fk, r.src_fk, r.dest_fk, aa.arrive_dt "
                                      "FROM requests as r "
                                      "JOIN asset_at as aa ON r.asset_fk = aa.asset_fk "
                                      "WHERE request_pk = %s;")
            selected_request_record = db_query(selected_request_query, [selected_request])

            # Both load and unload date submitted
            if load_date and unload_date:
                # Impossible use case
                if load_date > unload_date:
                    flash(
                        'It is not possible for an asset to be loaded after '
                        'it was unloaded. Make sure you entered your '
                        'dates correctly.'
                    )
                else:
                    # Check for logical dates...
                    transit_update = ("UPDATE in_transit SET load_dt = %s, unload_dt = %s "
                                      "WHERE request_fk = %s;")
                    db_change(transit_update, [
                        load_date, unload_date, selected_request]
                    )

                    update_asset_at = ("UPDATE asset_at SET depart_dt = %s "
                                       "WHERE asset_fk = %s AND arrive_dt = %s;")
                    db_change(update_asset_at, [
                        load_date, selected_request_record[0][1], selected_request_record[0][4]]
                    )

                    new_asset_at = ("INSERT INTO asset_at (asset_fk, facility_fk, arrive_dt) "
                                    "VALUES (%s, %s, %s);")
                    db_change(new_asset_at, [
                        selected_request_record[0][1], selected_request_record[0][3], unload_date]
                    )

                    update_request = "UPDATE requests SET completed = TRUE WHERE request_pk = %s;"
                    db_change(update_request, [
                        selected_request]
                    )

                    flash('Transfer Completed - Request Completed')

            # Updating only load date
            elif load_date and not unload_date:
                transit_update = "UPDATE in_transit SET load_dt = %s WHERE request_fk = %s;"
                db_change(transit_update, [
                        load_date, selected_request]
                )

                update_asset_at = ("UPDATE asset_at SET depart_dt = %s "
                                   "WHERE asset_fk = %s AND arrive_dt = %s;")
                db_change(update_asset_at, [
                        load_date, selected_request_record[0][1], selected_request_record[0][4]]
                )

                flash('Load Date Updated')

            # Attempting to only update unload date
            else:
                load_date = """
                SELECT r.request_pk, t.load_dt FROM requests as r
                JOIN in_transit as t ON r.request_pk = t.request_fk
                WHERE r.approved = TRUE AND r.request_pk = %s;
                """
                lo_requests = db_query(load_date, [selected_request])

                # There is no load date for this asset
                if not lo_requests[0][1]:
                    flash('The asset must be loaded before it can be unloaded.')

                # There is a load date for this asset-in-transit
                else:
                    transit_update = "UPDATE in_transit SET unload_dt = %s WHERE request_fk = %s;"
                    db_change(transit_update, [
                            unload_date, selected_request]
                    )

                    new_asset_at = ("INSERT INTO asset_at (asset_fk, facility_fk, arrive_dt) "
                                    "VALUES (%s, %s, %s);")
                    db_change(new_asset_at, [
                            selected_request_record[0][1],
                            selected_request_record[0][3],
                            unload_date
                        ]
                    )

                    update_request = "UPDATE requests SET completed = TRUE WHERE request_pk = %s;"
                    db_change(update_request, [
                            selected_request]
                    )

                    flash('Unload Date Updated! Transfer Completed - Request Completed')

            # Populate Table
            requests_query = ("SELECT r.request_pk, a.asset_tag, r.user_fk, "
                              "f1.common_name, f2.common_name, t.load_dt, t.unload_dt "
                              "FROM requests as r JOIN assets as a ON r.asset_fk = a.asset_pk "
                              "JOIN facilities as f1 on r.src_fk = f1.facility_pk "
                              "JOIN facilities as f2 on r.dest_fk = f2.facility_pk "
                              "JOIN in_transit as t ON r.request_pk = t.request_fk "
                              "WHERE r.approved = TRUE AND r.completed = FALSE;")
            lo_requests = db_query(requests_query, [])

            if lo_requests is None:
                lo_requests = [
                    ('NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS',
                     'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS')
                ]

            return render_template('dashboard.html', user=cur_user, requests=lo_requests)

        # FACILITY OFFICER
        elif session['perms'] == 3:
            selected_request = request.form.get('request_pk', None)

            # Nothing Selected
            if not selected_request:
                flash('Please select a request.')

            # No requests in DB
            elif selected_request == 'NO REQUESTS':
                flash('There are no requests to approve/disapprove.')

            # Something selected
            else:
                # Request rejected (Marked as completed)
                if 'reject' in request.form:
                    reject_request = "UPDATE requests SET completed = TRUE WHERE request_pk = %s;"
                    db_change(reject_request, [selected_request])
                    flash('Request DENIED.')

                # Request Approved
                else:
                    update_request_sql = ("UPDATE requests SET "
                                          "approved = TRUE, "
                                          "approving_user_fk = %s, "
                                          "approve_dt = %s "
                                          "WHERE request_pk = %s;")
                    db_change(update_request_sql, [
                            session['user_id'], datetime.datetime.now(), selected_request]
                    )

                    transit_sql = "INSERT INTO in_transit (request_fk) VALUES (%s);"
                    db_change(transit_sql, [selected_request])

                    flash('Request APPROVED.')

            # Populate Table
            requests_query = ("SELECT r.request_pk, a.asset_tag, r.user_fk, "
                              "f1.common_name, f2.common_name FROM requests as r "
                              "JOIN assets as a ON r.asset_fk = a.asset_pk "
                              "JOIN facilities as f1 ON r.src_fk = f1.facility_pk "
                              "JOIN facilities as f2 ON r.dest_fk = f2.facility_pk "
                              "WHERE r.approved = FALSE AND r.completed = FALSE;")
            fo_requests = db_query(requests_query, [])

            if fo_requests is None:
                fo_requests = [
                    ('NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS')
                ]

            return render_template('dashboard.html', user=cur_user, requests=fo_requests)

    # GET METHOD
    else:
        # LOGISTICS OFFICER
        if session['perms'] == 2:
            requests_query = ("SELECT r.request_pk, a.asset_tag, r.user_fk, "
                              "f1.common_name, f2.common_name, t.load_dt, t.unload_dt "
                              "FROM requests as r JOIN assets as a ON r.asset_fk = a.asset_pk "
                              "JOIN facilities as f1 on r.src_fk = f1.facility_pk "
                              "JOIN facilities as f2 on r.dest_fk = f2.facility_pk "
                              "JOIN in_transit as t ON r.request_pk = t.request_fk "
                              "WHERE r.approved = TRUE AND r.completed = FALSE;")
            lo_requests = db_query(requests_query, [])

            if lo_requests is None:
                lo_requests = [
                    ('NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS',
                     'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS')
                ]

            return render_template('dashboard.html', user=cur_user, requests=lo_requests)

        # FACILITY OFFICER
        elif session['perms'] == 3:
            requests_query = ("SELECT r.request_pk, a.asset_tag, r.user_fk, "
                              "f1.common_name, f2.common_name FROM requests as r "
                              "JOIN assets as a ON r.asset_fk = a.asset_pk "
                              "JOIN facilities as f1 ON r.src_fk = f1.facility_pk "
                              "JOIN facilities as f2 ON r.dest_fk = f2.facility_pk "
                              "WHERE r.approved = FALSE AND r.completed = FALSE;")
            fo_requests = db_query(requests_query, [])

            if fo_requests is None:
                fo_requests = [
                    ('NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS', 'NO REQUESTS')
                ]

            return render_template('dashboard.html', user=cur_user,
                                   requests=fo_requests)

        else:
            flash('You do not have access. Please login or create an account.')
            redirect(url_for('login'))


@app.route('/approve_req', methods=['GET'])
def approve_req():
    if session['perms'] == 3:
        pass
    else:
        flash('You must be a facility officer to approve requests.')
    return redirect(url_for('dashboard'))


@app.route('/update_transit', methods=['GET'])
def update_transit():
    if session['perms'] == 2:
        pass
    else:
        flash('You must be a logistics officer to update transit records.')
    return redirect(url_for('dashboard'))


@app.route('/add_facility', methods=['GET', 'POST'])
def add_facility():
    if request.method == 'POST':
        fcode = request.form.get('fcode', None).strip()
        common_name = request.form.get('common_name', None)
        location = request.form.get('location', None)

        # Get all current facilities for table population
        all_facilities = db_query("SELECT * FROM facilities;", [])

        # If something is missing from the form...
        if not fcode or not common_name or not location:
            flash('Please complete the form')
            return render_template('add_facility.html', data=all_facilities)

        else:
            # Check for duplicate entry attempt...
            matching_facilities = ("SELECT facility_pk FROM facilities "
                                   "WHERE fcode=%s OR common_name=%s;")
            facility_does_exist = duplicate_check(matching_facilities, [fcode, common_name])

            if facility_does_exist:
                flash('There already exists a facility with that fcode or common name!')
                return render_template('add_facility.html', data=all_facilities)

            # Facility does not already exist - create it
            else:
                new_facility = ("INSERT INTO facilities (fcode, common_name, location) "
                                "VALUES (%s, %s, %s);")
                db_change(new_facility, [fcode, common_name, location])
                flash('New facility was created!')

    # Update all_facilities after insert, but before template rendering
    all_facilities = db_query("SELECT * FROM facilities;", [])

    # Database doesn't have any facilities yet.
    if all_facilities is None:
        all_facilities = [('NO FACILITIES', 'NO FACILITIES', 'NO FACILITIES')]


    return render_template('add_facility.html', data=all_facilities)


@app.route('/add_asset', methods=['GET', 'POST'])
def add_asset():
    # Create queries to populate dropdown menu and current assets table
    all_assets_query = ("SELECT assets.asset_tag, assets.description, facilities.location "
                        "FROM assets "
                        "JOIN asset_at ON assets.asset_pk = asset_at.asset_fk "
                        "JOIN facilities ON asset_at.facility_fk = facilities.facility_pk;")
    all_facilities_query = "SELECT * FROM facilities;"

    if request.method == 'POST':
        asset_tag = request.form.get('asset_tag', None).strip()
        description = request.form.get('description', None)
        facility = request.form.get('facility')
        date = request.form.get('date')
        disposed = False

        # Get all current assets and facilities for table/drop-down population
        all_assets = db_query(all_assets_query, [])
        all_facilities = db_query(all_facilities_query, [])

        if all_facilities is None:
            flash('You must add facilities before you can get asset reports.')
            return redirect(url_for('dashboard'))

        # Handle table when no assets in database
        if all_assets is None:
            all_assets = [
                ('NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES')
            ]

        # If something is missing from the form...
        if not asset_tag or not description or not date or facility == '':
            flash('Please complete the form')
            return render_template(
                'add_asset.html', assets_list=all_assets, facilities_list=all_facilities
            )
        else:
            try:
                validated_date = validate_date(date)
            except ValueError or TypeError or UnboundLocalError:
                flash('Please enter the date in the following format: MM/DD/YYYY')
                return render_template(
                    'add_asset.html', assets_list=all_assets, facilities_list=all_facilities
                )

            # Check for duplicate entry attempt...
            matching_assets = "SELECT asset_pk FROM assets WHERE asset_tag=%s;"
            asset_does_exist = duplicate_check(matching_assets, [asset_tag])

            if asset_does_exist:
                flash('There already exists an asset with that tag!')
            else:
                # Asset does not already exist - create it...
                new_asset = ("INSERT INTO assets (asset_tag, description, disposed) "
                             "VALUES (%s, %s, %s);")
                db_change(new_asset, [asset_tag, description, disposed])

                # Get Asset Key for asset_at insertion
                recently_added_asset = "SELECT asset_pk FROM assets WHERE asset_tag = %s;"
                asset_fk = db_query(recently_added_asset, [asset_tag])

                # Insert asset_at record for newly added asset
                new_asset_at = ("INSERT INTO asset_at (asset_fk, facility_fk, arrive_dt) "
                                "VALUES (%s, %s, %s);")
                db_change(new_asset_at, [asset_fk[0][0], facility, validated_date])

                flash('New asset added!')

    # Get Facilities for dropdown
    all_facilities = db_query(all_facilities_query, [])
    if all_facilities is None:
        flash('You must add facilities before you can get asset reports.')
        return redirect(url_for('dashboard'))

    # Update all_assets after insert, but before template rendering
    all_assets = db_query(all_assets_query, [])
    # Handle situation of no assets in database
    if all_assets is None:
        all_assets = [('NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES')]

    return render_template('add_asset.html', assets_list=all_assets, facilities_list=all_facilities)


# TODO: Implement functionality for asset being set to disposed if moved from original facility
@app.route('/dispose_asset', methods=['GET', 'POST'])
def dispose_asset():
    # Not a logistics officer...
    if session.get('perms') != 2:
        flash('You are not a Logistics Officer. You do not have permissions to remove assets!')
        return render_template('dashboard.html')

    # Get all current assets for table population
    else:
        all_assets_query = ("SELECT assets.asset_tag, assets.description, "
                            "facilities.location, assets.disposed "
                            "FROM assets JOIN asset_at ON assets.asset_pk = asset_at.asset_fk "
                            "JOIN facilities ON asset_at.facility_fk = facilities.facility_pk;")
        all_assets = db_query(all_assets_query, [])

        # Handle table when no assets in database
        if all_assets is None:
            all_assets = [(
                'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES'
            )]
            flash('There are currently no assets to remove')
            return render_template('dispose_asset.html', assets_list=all_assets)

        if request.method == 'POST':
            asset_tag = request.form.get('asset_tag', None).strip()
            date = request.form.get('date')

            # If something is missing from the form...
            if not asset_tag or not date:
                flash('Please complete the form')
                return render_template('dispose_asset.html', assets_list=all_assets)
            else:
                try:
                    validated_date = validate_date(date)
                except ValueError or TypeError or UnboundLocalError:
                    flash('Please enter the date in the following format: MM/DD/YYYY')
                    return render_template('dispose_asset.html', assets_list=all_assets)

                # Check for matching tag...
                matching_asset = "SELECT asset_pk FROM assets WHERE asset_tag = %s;"
                asset_does_exist = duplicate_check(matching_asset, [asset_tag])

                if asset_does_exist:
                    # Get asset_fk for asset_at update (returns a tuple in an array)
                    asset_fk = db_query(matching_asset, [asset_tag])[0][0]

                    # Change asset_at table to reflect impending disposal
                    update_asset_at = "UPDATE asset_at SET depart_dt=%s WHERE asset_fk=%s;"
                    db_change(update_asset_at, [validated_date, asset_fk])

                    # Remove asset from assets
                    asset_to_dispose = "UPDATE assets SET disposed=TRUE WHERE asset_tag = %s;"
                    db_change(asset_to_dispose, [asset_tag])

                    # Update current assets for view's table ('disposed' column will have changed)
                    all_assets = db_query(all_assets_query, [])

                    # Handle table when no assets in database
                    if all_assets is None:
                        all_assets = [(
                            'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES'
                        )]

                    flash('Asset removed!')
                    return render_template('dispose_asset.html', assets_list=all_assets)

                else:
                    flash('There does not exist an asset with that tag!')
                    return render_template('dispose_asset.html', assets_list=all_assets)

        return render_template('dispose_asset.html', assets_list=all_assets)


@app.route('/asset_report', methods=['GET', 'POST'])
def asset_report():
    all_facilities_query = "SELECT * FROM facilities;"

    # If a form has been submitted...
    if request.method == 'POST':
        # List of single-tuples of all facilities to populate drop-down
        all_facilities = db_query(all_facilities_query, [])
        if all_facilities is None:
            flash('You must add facilities before you can get asset reports.')
            return redirect(url_for('dashboard'))

        # User Input from Form
        facility = request.form.get('facility')
        date = request.form.get('date')

        # Validate Inputs
        if not date:
            flash('Please complete the form')
            return render_template(
                'asset_report.html', facilities_list=all_facilities, report=False
            )
        else:
            try:
                validated_date = validate_date(date)
            except ValueError or TypeError or UnboundLocalError:
                flash(
                    'Please enter the date in the following format: MM/DD/YYYY')
                return render_template(
                    'asset_report.html', facilities_list=all_facilities, report=False
                )

        # Get all assets at all facilities
        if facility == 'All':
            all_assets_report = ("SELECT a.asset_tag, a.description, f.location, "
                                 "a_a.arrive_dt, a_a.depart_dt FROM assets as a "
                                 "JOIN asset_at as a_a ON a.asset_pk = a_a.asset_fk "
                                 "JOIN facilities as f ON a_a.facility_fk = f.facility_pk "
                                 "WHERE (a_a.depart_dt >= %s OR a_a.depart_dt IS NULL) "
                                 "AND a_a.arrive_dt <= %s;")
            all_assets = db_query(
                all_assets_report, [validated_date, validated_date]
            )

            # No Results
            if all_assets is None:
                all_assets = [(
                    'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES'
                )]

            # Handle <h4> at top of asset_report for all facilities option - searched by facility[2]
            facility = ['', '', 'all facilities']

            return render_template(
                'asset_report.html', facility=facility, date=validated_date,
                assets_list=all_assets, facilities_list=all_facilities, report=True
            )

        # Get all assets at a specific facility
        else:
            individual_facility_report = ("SELECT a.asset_tag, a.description, "
                                          "f.location, a_a.arrive_dt, a_a.depart_dt "
                                          "FROM assets as a "
                                          "JOIN asset_at as a_a ON a.asset_pk = a_a.asset_fk "
                                          "JOIN ("
                                          "SELECT facility_pk, location FROM facilities "
                                          "WHERE facility_pk = %s"
                                          ") as f ON f.facility_pk = a_a.facility_fk "
                                          "WHERE (a_a.depart_dt >= %s OR a_a.depart_dt IS NULL) "
                                          "AND a_a.arrive_dt <= %s;")
            filtered_assets = db_query(
                individual_facility_report, [facility, validated_date, validated_date]
            )

            # No Results
            if filtered_assets is None:
                filtered_assets = [(
                    'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES', 'NO ENTRIES'
                )]

            # Handle <h4> at top of asset_report for all facilities option - searched by facility[2]
            facility = filtered_assets[0]

            return render_template('asset_report.html', facility=facility, date=validated_date,
                                   assets_list=filtered_assets, facilities_list=all_facilities,
                                   report=True)

    # List of single-tuples of all facilities to populate drop-down
    all_facilities = db_query(all_facilities_query, [])
    if all_facilities is None:
        flash('You must add facilities to the database before you can get asset reports.')
        return redirect(url_for('dashboard'))

    return render_template('asset_report.html', facilities_list=all_facilities, report=False)


@app.route('/transfer_report', methods=['GET', 'POST'])
def transfer_report():
    return render_template('transfer_report.html')


@app.route('/transfer_req', methods=['GET', 'POST'])
def transfer_req():
    # Not a logistics officer...
    if session.get('perms') != 2:
        flash('You are not a Logistics Officer. You do not have permissions to request transfers!')
        return render_template('dashboard.html')

    request_is_post = False
    if request.method == 'POST':
        request_is_post = True
        asset_key = request.form['asset']
        src_facility = request.form['src_facility']
        dest_facility = request.form['dest_facility']

        # Form Completion Validation
        if asset_key == '':
            flash('Please select an asset.')
            return redirect(url_for('transfer_req'))
        elif src_facility == '' or dest_facility == '':
            flash('Please select a facility.')
            return redirect(url_for('transfer_req'))

        location_query = ("SELECT asset_at.facility_fk FROM asset_at "
                          "JOIN assets ON asset_at.asset_fk = assets.asset_pk "
                          "WHERE asset_pk = %s;")
        actual_asset_location = db_query(location_query, [asset_key])

        if actual_asset_location is None:
            flash('There is either no facilities or assets in the database.')
            return redirect(url_for('dashboard'))

        if src_facility != str(actual_asset_location[0][0]):
            flash('The source facility you selected is not where the asset is stored.')
            return redirect(url_for('transfer_req'))
        elif dest_facility == src_facility:
            flash('Please select different facilities in order to submit a transfer request.')
            return redirect(url_for('transfer_req'))

        # Inputs Validated
        else:
            request_sql = ("INSERT INTO requests "
                           "(asset_fk, user_fk, src_fk, dest_fk, request_dt, approved, completed) "
                           "VALUES "
                           "(%s, %s, %s, %s, %s, 'False', 'False');")

            db_change(
                request_sql, [
                    asset_key,
                    session['user_id'],
                    src_facility,
                    dest_facility,
                    datetime.datetime.now()
                ]
            )

            flash('Request Submitted. Please await Facility Officer approval.')

    # Query relevant data for dropdown selections
    # Facilities
    all_facilities_query = "SELECT * FROM facilities;"
    all_facilities = db_query(all_facilities_query, [])

    if all_facilities is None:
        flash('You must add facilities to the database before you can create transfer requests.')
        return redirect(url_for('dashboard'))

    # Assets
    all_assets_query = ("SELECT * FROM assets WHERE asset_pk NOT IN "
                        "(SELECT asset_fk FROM requests "
                        "WHERE completed='FALSE' AND approved='FALSE';)"
                        ";")
    all_assets = db_query(all_assets_query, [])

    # Handle empty result query cases
    if request_is_post and all_assets is None:
        flash('You must add assets to the database before you can create transfer requests.')
        return redirect(url_for('dashboard'))

    return render_template('transfer_req.html', asset_list=all_assets, facility_list=all_facilities)


# MARK: ERROR PAGES
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.route('/failed_query', methods=['GET'])
def failed_query(query):
    return render_template('failed_query.html', query=query)


# Application Deployment
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
