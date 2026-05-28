

init_data()

if __name__ == '__main__':
    init_db()
    conn = get_conn()
    conn.execute('DELETE FROM attractions')
    conn.execute('DELETE FROM foods')
    conn.execute('DELETE FROM sqlite_sequence')
    conn.commit()
    conn.close()
    build_all()
    print('Build complete!')
