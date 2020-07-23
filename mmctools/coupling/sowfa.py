#!/usr/bin/env python

'''
Tools for generating SOWFA MMC inputs
'''

__author__ = "Dries Allaerts"
__date__   = "May 16, 2019"

import numpy as np
import pandas as pd
import os

import gzip as gz


boundaryDataHeader = """/*--------------------------------*- C++ -*----------------------------------*\\
  =========                 |
  \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\\\    /   O peration     | Website:  https://openfoam.org
    \\\\  /    A nd           | Version:  6
     \\\\/     M anipulation  |
\\*---------------------------------------------------------------------------*/

// generated by mmctools.coupling.sowfa.BoundaryCoupling
// https://github.com/a2e-mmc/mmctools/tree/dev

{N:d}
("""


class InternalCoupling(object):
    """
    Class for writing data to SOWFA-readable input files for internal coupling
    """
    def __init__(self,
                 dpath,
                 df,
                 dateref=None,
                 datefrom=None,
                 dateto=None):
        """
        Initialize SOWFA input object

        Usage
        =====
        dpath : str
            Folder to write files to
        df : pandas.DataFrame
            Data (index should be called datetime)
        dateref : str, optional
            Reference datetime, used to construct a pd.DateTimeIndex
            with SOWFA time 0 corresponding to dateref; if not
            specified, then the time index will be the simulation time
            as a pd.TimedeltaIndex
        datefrom : str, optional
            Start date of the period that will be written out, if None
            start from the first timestamp in df; only used if dateref
            is specified
        dateto : str, optional
            End date of the period that will be written out, if None end
            with the last timestamp in df; only used if dateref is
            specified
        """
        
        self.dpath = dpath
        # Create folder dpath if needed
        if not os.path.isdir(dpath):
            os.mkdir(dpath)

        # Handle input with multiindex
        if isinstance(df.index, pd.MultiIndex):
            assert df.index.names[0] == 'datetime', 'first multiindex level is not "datetime"'
            assert df.index.names[1] == 'height', 'second multiindex level is not "height"'
            df = df.reset_index(level=1)

        # Use dataframe between datefrom and dateto
        if datefrom is None:
            datefrom = df.index[0]
        if dateto is None:
            dateto = df.index[-1]
        # Make copy to avoid SettingwithcopyWarning
        self.df = df.loc[(df.index>=datefrom) & (df.index<=dateto)].copy()
        assert(len(self.df.index.unique())>0), 'No data for requested period of time'
        
        # Store start date for ICs
        self.datefrom = datefrom

        # calculate time in seconds since reference date
        if dateref is not None:
            # self.df['datetime'] exists and is a DateTimeIndex
            dateref = pd.to_datetime(dateref)
            tdelta = pd.Timedelta(1,unit='s')
            self.df.reset_index(inplace=True)
            self.df['t_index'] = (self.df['datetime'] - dateref) / tdelta
            self.df.set_index('datetime',inplace=True)
        elif isinstance(df.index, pd.TimedeltaIndex):
            # self.df['t'] exists and is a TimedeltaIndex
            self.df['t_index'] = self.df.index.total_seconds()
        else:
            self.df['t_index'] = self.df.index

    def write_BCs(self,
                  fname,
                  fieldname,
                  fact=1.0
                  ):
        """
        Write surface boundary conditions to SOWFA-readable input file for
        solver (to be included in $startTime/qwall)
    
        Usage
        =====
        fname : str
            Filename
        fieldname : str
            Name of the field to be written out
        fact : float
            Scale factor for the field, e.g., to scale heat flux to follow
            OpenFOAM sign convention that boundary fluxes are positive if
            directed outward
        """
    
        # extract time and height array
        ts = self.df.t_index.values
        nt = ts.size
    
        # assert field exists and is complete
        assert(fieldname in self.df.columns), 'Field '+fieldname+' not in df'
        assert(~pd.isna(self.df[fieldname]).any()), 'Field '+fieldname+' is not complete (contains NaNs)'
    
        # scale field with factor,
        # e.g., scale heat flux with fact=-1 to follow OpenFOAM sign convention
        fieldvalues = fact * self.df[fieldname].values
    
        with open(os.path.join(self.dpath,fname),'w') as fid:
            fmt = ['    (%g', '%.12g)',]
            np.savetxt(fid,np.concatenate((ts.reshape((nt,1)),
                                          fieldvalues.reshape((nt,1))
                                          ),axis=1),fmt=fmt)
    
        return


    def write_ICs(self,
                  fname,
                  xmom = 'u',
                  ymom = 'v',
                  temp = 'theta',
                  ):
        """
        Write initial conditions to SOWFA-readable input file for setFieldsABL
    
        Usage
        =====
        fname : str
            Filename
        xmom : str
            Field name corresponding to the x-velocity
        ymom : str
            Field name corresponding to the y-velocity
        temp : str
            Field name corresponding to the potential temperature
        """
        
        # Make copy to avoid SettingwithcopyWarning
        df = self.df.loc[self.datefrom].copy()

        # set missing fields to zero
        fieldNames = [xmom, ymom, temp]
        for field in fieldNames:
            if not field in df.columns:
                df.loc[:,field] = 0.0
    
        # extract time and height array
        zs = df.height.values
        nz = zs.size
    
        # check data is complete
        for field in fieldNames:
            assert ~pd.isna(df[field]).any()
    
        # write data to SOWFA readable file
        with open(os.path.join(self.dpath,fname),'w') as fid:
            fmt = ['    (%g',] + ['%.12g']*2 + ['%.12g)',]
            np.savetxt(fid,np.concatenate((zs.reshape((nz,1)),
                                           df[xmom].values.reshape((nz,1)),
                                           df[ymom].values.reshape((nz,1)),
                                           df[temp].values.reshape((nz,1))
                                          ),axis=1),fmt=fmt)
        return


    def write_timeheight(self,
                         fname,
                         xmom=None,
                         ymom=None,
                         zmom=None,
                         temp=None,
                         ):
        """
        Write time-height data to SOWFA-readable input file for solver
        (to be included in constant/ABLProperties). Note that if any
        momentum data output is specified, then all components should be
        specified together for SOWFA to function properly.
    
        Usage
        =====
        fname : str
            Filename
        xmom : str or None
            Field name corresponding to x momentum (field or tendency)
        ymom : str or None
            Field name corresponding to y momentum (field or tendency)
        zmom : str or None
            Field name corresponding to z momentum (field or tendency)
        temp : str or None
            Field name corresponding to potential temperature (field or tendency)
        """
        have_xyz_mom = [(comp is not None) for comp in [xmom,ymom,zmom]]
        if any(have_xyz_mom):
            assert all(have_xyz_mom), 'Need to specify all momentum components'
            write_mom = True
        else:
            write_mom = False
    
        # extract time and height array
        zs = self.df.height.unique()
        ts = self.df.t_index.unique()
        nz = zs.size
        nt = ts.size
    
        # set missing fields to zero
        fieldNames = [xmom, ymom, zmom, temp]
        for field in fieldNames:
            if (field is not None) and (field not in self.df.columns):
                self.df.loc[:,field] = 0.0
        fieldNames = [name for name in fieldNames if name is not None]
    
        # pivot data to time-height arrays
        df_pivot = self.df.pivot(columns='height',values=fieldNames)
        # check data is complete
        for field in fieldNames:
            assert ~pd.isna(df_pivot[field]).any().any()
    
        # write data to SOWFA readable file
        with open(os.path.join(self.dpath,fname),'w') as fid:
            if write_mom:
                # Write the height list for the momentum fields
                fid.write('sourceHeightsMomentum\n')    
                np.savetxt(fid,zs,fmt='    %g',header='(',footer=');\n',comments='')
                  
                # Write the x-velocity
                fid.write('sourceTableMomentumX\n')
                fmt = ['    (%g',] + ['%.12g']*(nz-1) + ['%.12g)',]
                np.savetxt(fid,
                           np.concatenate((ts.reshape((nt,1)),df_pivot[xmom].values),axis=1),
                           fmt=fmt, header='(', footer=');\n', comments='')
    
                # Write the y-velocity
                fid.write('sourceTableMomentumY\n')
                fmt = ['    (%g',] + ['%.12g']*(nz-1) + ['%.12g)',]
                np.savetxt(fid,
                           np.concatenate((ts.reshape((nt,1)),df_pivot[ymom].values),axis=1),
                           fmt=fmt, header='(', footer=');\n', comments='')
    
                # Write the z-velocity
                fid.write('sourceTableMomentumZ\n')
                fmt = ['    (%g',] + ['%.12g']*(nz-1) + ['%.12g)',]
                np.savetxt(fid,
                           np.concatenate((ts.reshape((nt,1)),df_pivot[zmom].values),axis=1),
                           fmt=fmt, header='(', footer=');\n', comments='')
    
            if temp:
                # Write the height list for the temperature fields
                fid.write('sourceHeightsTemperature\n') 
                np.savetxt(fid,zs,fmt='    %g',header='(',footer=');\n',comments='')
        
                # Write the temperature
                fid.write('sourceTableTemperature\n')
                fmt = ['    (%g',] + ['%.12g']*(nz-1) + ['%.12g)',]
                np.savetxt(fid,
                           np.concatenate((ts.reshape((nt,1)),df_pivot[temp].values),axis=1),
                           fmt=fmt, header='(', footer=');\n', comments='')
    
        return


class BoundaryCoupling(object):
    """
    Class for writing data to SOWFA-readable input files for boundary coupling
    """
    def __init__(self,
                 dpath,
                 ds,
                 name='patch',
                 dateref=None,
                 datefrom=None,
                 dateto=None):
        """
        Initialize SOWFA input object. This should be called for _each_
        inflow/outflow boundary.

        Usage
        =====
        dpath : str
            Folder to write files to
        ds : xarray.Dataset
            Data (dimensions should be: datetime, height, x, y)
        name : str
            Name of patch, corresponding to the constnat/boundaryData
            subdirectory
        dateref : str, optional
            Reference datetime, used to construct a pd.DateTimeIndex
            with SOWFA time 0 corresponding to dateref; if not
            specified, then the time index will be the simulation time
            as a pd.TimedeltaIndex
        datefrom : str, optional
            Start date of the period that will be written out, if None
            start from the first timestamp in df; only used if dateref
            is specified
        dateto : str, optional
            End date of the period that will be written out, if None end
            with the last timestamp in df; only used if dateref is
            specified
        """
        self.name = name
        self.dpath = os.path.join(dpath, name)
        # Create folder dpath if needed
        if not os.path.isdir(self.dpath):
            os.makedirs(self.dpath)

        # Check xarray coordinates
        self.ds = ds
        self._check_xarray_dataset()
        
        # Use dataframe between datefrom and dateto
        if datefrom is None:
            datefrom = ds.coords['datetime'][0]
        else:
            datefrom = pd.to_datetime(datefrom)
        if dateto is None:
            dateto = ds.coords['datetime'][-1]
        else:
            dateto = pd.to_datetime(dateto)
        self.ds = self.ds.sel(datetime=slice(datefrom,dateto))

        # Store start date for ICs
        self.datefrom = datefrom

        # calculate time in seconds since reference date
        if dateref is None:
            dateref = self.ds.coords['datetime'][0]
        else:
            dateref = pd.to_datetime(dateref)
        tidx = (self.ds['datetime'] - dateref.to_datetime64()) / np.timedelta64(1,'s')
        self.ds = self.ds.assign_coords(t_index=('datetime',tidx))

    def _check_xarray_dataset(self,
                              expected_dims=['datetime','height','x','y']):
        """Do all sanity checks here"""
        for dim in self.ds.dims:
            # dimension coordinates
            assert dim in expected_dims
            coord = self.ds.coords[dim]
            assert (coord.dims[0] == dim) and (len(coord.dims) == 1)
        # Only handle a single boundary plane at a time; boundaries
        # should be aligned with the Cartesian axes
        dims = expected_dims.copy()
        for dim in self.ds.dims:
            dims.remove(dim)
        assert (len(dims) == 1)
        constdim = dims[0]
        print('Input is an {:s}-boundary at {:g}'.format(constdim,
                                                         self.ds.coords[constdim].values))
        
    def write(self, fields, binary=False, gzip=False):
        """
        Write surface boundary conditions to SOWFA-readable input files
        for the solver in constant/boundaryData
    
        Usage
        =====
        patchname : str
            Name of patch subdirectory
        fields : dict
            Key-value pairs with keys corresponding to the OpenFOAM
            field name, values corresponding to dataset data variables;
            values may be a single variable (scalar) or a list/tuple of
            variables (vector)
        binary : bool, optional
            Write out actual data (coordinates, scalars, vectors) in
            binary for faster I/O
        """
        # check output options
        if binary and gzip:
            print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
            print('! Note: Compressed binary is inefficient.                   !')
            print('! You probably want:                                        !')
            print('! * uncompressed binary (most efficient for openfoam), or   !')
            print('! * compressed ascii (readable for debug, less space usage) !')
            print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
        # make sure ordering of bnd_dims is correct
        dims = list(self.ds.dims)
        dims.remove('datetime')
        self.bndry_dims = [dim for dim in ['x','y','height'] if dim in dims]
        assert (len(self.bndry_dims) == 2)
        # write out patch/points
        self._write_points(binary=binary, gzip=gzip)
        # write out patch/*/field
        for fieldname,dvars in fields.items():
            if isinstance(dvars, (list,tuple)):
                # vector
                assert all([dvar in self.ds.variables for dvar in dvars]), \
                        'Dataset does not contain all of '+str(dvars)
                assert (len(dvars) == 3)
                self._write_boundary_vector(fieldname, components=dvars,
                                            binary=binary, gzip=gzip)
            else:
                # scalar
                assert (dvars in self.ds.variables)
                self._write_boundary_scalar(fieldname, var=dvars,
                                            binary=binary, gzip=gzip)

    def _open(self,fpath,fopts,gzip=False):
        if gzip:
            if not fpath.endswith('.gz'):
                fpath += '.gz'
            return gz.open(fpath, fopts)
        else:
            return open(fpath, fopts)

    def _write_points(self,fname='points',binary=False,gzip=False):
        x,y,z = np.meshgrid(self.ds.coords['x'],
                            self.ds.coords['y'],
                            self.ds.coords['height'],
                            indexing='ij')
        x = x.ravel(order='C')
        y = y.ravel(order='C')
        z = z.ravel(order='C')
        N = len(x)
        pts = np.stack((x,y,z),axis=1)  # shape == (N,3)
        fpath = os.path.join(self.dpath, fname)
        header = boundaryDataHeader.format(N=N)
        if binary:
            with self._open(fpath, 'wb', gzip=gzip) as f:
                f.write(bytes(header,'utf-8'))
                f.write(pts.tobytes(order='C'))
                f.write(b')')
        else:
            with self._open(fpath, 'w', gzip=gzip) as f:
                np.savetxt(f, pts, fmt='(%g %g %g)', header=header, footer=')', comments='')
        print('Wrote',N,'points to',fpath)

    def _write_boundary_vector(self,fname,components,binary=False,gzip=False):
        ds = self.ds.copy()
        # add missing dimensions, if any
        for dim in self.bndry_dims:
            for var in components:
                if dim not in ds[var].dims:
                    ds[var] = ds[var].expand_dims({dim: ds.coords[dim]})
        #print(ds[list(components)])
        # reorder the data so that raveling produces the correct order
        dim_order = ['t_index'] + self.bndry_dims
        uvec = [
            ds[var].swap_dims({'datetime':'t_index'}).transpose(*dim_order)
            for var in components
        ]
        for ui,vi,wi in zip(*uvec):
            ti = float(ui['t_index'])
            if ti < 0:
                print('Skipping t=',ti)
                continue
            tstamp = ui['datetime'].values
            tname = '{:g}'.format(ti)
            ui = ui.values.ravel(order='C')
            vi = vi.values.ravel(order='C')
            wi = wi.values.ravel(order='C')
            data = np.stack((ui,vi,wi), axis=1)  # shape == (N,3)
            N = len(data)
            dpath = os.path.join(self.dpath,tname)
            fpath = os.path.join(dpath,fname)
            if not os.path.isdir(dpath):
                os.makedirs(dpath)
            header = boundaryDataHeader.format(N=N)
            if binary:
                with self._open(fpath, 'wb', gzip=gzip) as f:
                    f.write(bytes(header,'utf-8'))
                    f.write(data.tobytes(order='C'))
                    f.write(b')')
                    f.write(b'\n(0 0 0)')
            else:
                with self._open(fpath ,'w', gzip=gzip) as f:
                    np.savetxt(f, data, fmt='(%g %g %g)', header=header, footer=')', comments='')
                    if gzip:
                        f.write(b'\n(0 0 0) // average value')
                    else:
                        f.write('\n(0 0 0) // average value')
            print('Wrote',N,'vectors to',fpath,'at',str(tstamp))

    def _write_boundary_scalar(self,fname,var,binary=False,gzip=False):
        ds = self.ds.copy()
        # add missing dimensions, if any
        for dim in self.bndry_dims:
            if dim not in ds[var].dims:
                ds[var] = ds[var].expand_dims({dim: ds.coords[dim]})
        # reorder the data so that raveling produces the correct order
        dim_order = ['t_index'] + self.bndry_dims
        u = ds[var].swap_dims({'datetime':'t_index'}).transpose(*dim_order)
        for ui in u:
            ti = float(ui['t_index'])
            if ti < 0:
                print('Skipping t=',ti)
                continue
            tstamp = ui['datetime'].values
            tname = '{:g}'.format(ti)
            ui = ui.values.ravel(order='C')
            N = len(ui)
            dpath = os.path.join(self.dpath,tname)
            fpath = os.path.join(dpath,fname)
            if not os.path.isdir(dpath):
                os.makedirs(dpath)
            header = boundaryDataHeader.format(N=N)
            if binary:
                with self._open(fpath, 'wb', gzip=gzip) as f:
                    f.write(bytes(header,'utf-8'))
                    f.write(ui.tobytes(order='C'))
                    f.write(b')')
                    f.write(b'\n0')
            else:
                with self._open(fpath, 'w', gzip=gzip) as f:
                    np.savetxt(f, ui, fmt='%g', header=header, footer=')', comments='')
                    if gzip:
                        f.write(b'\n0 // average value')
                    else:
                        f.write('\n0 // average value')
            print('Wrote',N,'scalars to',fpath,'at',str(tstamp))
